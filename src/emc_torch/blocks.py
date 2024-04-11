""" prepare module to get and cast data needed for simulations"""
from emc_torch import options, functions, plotting
import logging
import torch
import numpy as np
import pathlib as plib
log_module = logging.getLogger(__name__)


#ToDo
# For pypulseq we can implement a pulse train straight from the events and kernels and ship it to the emc simulation
# all timings and shapes would be defined

class GradPulse:
    def __init__(self,
                 pulse_type: str = 'Excitation',
                 pulse_number: int = 0,
                 num_sampling_points: int = 512,
                 dt_sampling_steps_us: float = 5.0,
                 duration_us: float = 0.0):
        self.pulse_number = pulse_number
        self.pulse_type = pulse_type
        self.num_sampling_points = num_sampling_points
        self.dt_sampling_steps_us = dt_sampling_steps_us
        self.data_grad = torch.zeros(0)
        self.data_pulse_x = torch.zeros(0)
        self.data_pulse_y = torch.zeros(0)
        self.duration_us = duration_us

        # set and check
        self._set_exci_flag()

    def set_device(self, device: torch.device):
        self.data_pulse_x = self.data_pulse_x.to(device)
        self.data_pulse_y = self.data_pulse_y.to(device)
        self.data_grad = self.data_grad.to(device)

    def _set_exci_flag(self):
        if self.pulse_type == 'Excitation':
            self.excitation_flag = True
        else:
            self.excitation_flag = False

    def _set_float32(self):
        self.data_grad = self.data_grad.to(dtype=torch.float32)
        self.data_pulse_x = self.data_pulse_x.to(dtype=torch.float32)
        self.data_pulse_y = self.data_pulse_y.to(dtype=torch.float32)

    @classmethod
    def prep_grad_pulse_excitation(cls, params: options.SimulationParameters):
        log_module.debug(f"prep excitation pulse")

        params = cls._set_pulse(params=params, duration_us=params.sequence.duration_excitation, excitation=True)

        # calculate and normalize - pulse dims [b1, t]
        pulse_from_pypsi = functions.pulse_calibration_integral(
            sim_params=params,
            excitation=True
        )

        log_module.debug(f"\t PULSE + GRAD")

        gradient_read_pre_phase = 0.0
        if params.config.signal_fourier_sampling:
            # we want to sample the signal via a readout gradient (artificially moved into 1D slice),
            # and need to prephase this readout in the excitation rephasing in case we are using
            # the siemens mese sequence
            if params.config.sim_type == "mese_siemens":
                # when acquiring in k-space along the slice we need to move the k-space start to the corner of k-space
                # i.e.: prephase half an acquisition gradient moment, put it into the rephase timing
                gradient_read_pre_phase = params.sequence.gradient_acquisition * params.sequence.duration_acquisition / \
                                     (2 * params.sequence.duration_excitation_rephase)
                # the refocusing will then move to the opposite side of k-space

        grad, pulse, duration, area_grad = cls.build_pulse_grad_shapes(
            pulse=pulse_from_pypsi, grad_amp_slice_select=params.sequence.gradient_excitation,
            duration_pulse_slice_select_us=params.sequence.duration_excitation,
            grad_amp_post=params.sequence.gradient_excitation_rephase + gradient_read_pre_phase,
            duration_post_us=params.sequence.duration_excitation_rephase,
            grad_amp_verse_lobe=params.sequence.gradient_excitation_verse_lobes,
            duration_verse_lobe_us=params.sequence.duration_excitation_verse_lobes
        )
        # grad dim [dt], pulse dim [b1, dt]
        # assign vars
        grad_pulse = cls(
            pulse_number=0, pulse_type="Excitation",
            num_sampling_points=pulse_from_pypsi.shape[-1],
            dt_sampling_steps_us=params.sequence.duration_excitation / pulse_from_pypsi.shape[-1],
            duration_us=params.sequence.duration_excitation
        )
        grad_pulse.assign_data(grad=grad, pulse_cplx=pulse)
        return grad_pulse

    @classmethod
    def prep_grad_pulse_refocus(cls, params: options.SimulationParameters, refocus_pulse_number: int,
                                force_sym_spoil: bool = False):
        log_module.debug(f"prep refocusing pulse: {refocus_pulse_number + 1}")
        # -- prep pulse
        params = cls._set_pulse(params=params, duration_us=params.sequence.duration_refocus, excitation=False)
        # calculate and normalize
        pulse_from_pypsi = functions.pulse_calibration_integral(
            sim_params=params,
            excitation=False,
            refocusing_pulse_number=refocus_pulse_number
        )

        log_module.debug(f"\t PULSE + GRAD")
        gradient_read_pre_phase = 0.0
        if params.config.signal_fourier_sampling:
            # we want to sample the signal via a readout gradient (artificially moved into 1D slice),
            # and need to prephase this readout in the excitation rephasing in case we are using
            # the siemens mese sequence
            if not params.config.sim_type == "mese_siemens":
                # when acquiring in k-space along the slice we need to move the k-space start to the corner of k-space
                # i.e.: prephase half an acquisition gradient moment, put it into the refocusing crusher timing
                gradient_read_pre_phase = (
                        - params.sequence.gradient_acquisition * params.sequence.duration_acquisition /
                        (2 * params.sequence.duration_crush)
                )
                # in the balanced version the read gradient is prephased during end of refocusing, then read,
                # then rephased to 0 before next refocussing pulse, hence it must be added to both lobes (pre & post)

        # gradient before pulse = rephasing of read gradient plus spoiling
        gradient_slice_pre = params.sequence.gradient_crush + gradient_read_pre_phase
        if refocus_pulse_number == 0 and not force_sym_spoil:
            # on first refocusing pulse we dont need the symmetrical slice gradients
            # since its included in the rephaser of the excitation pulse
            gradient_slice_pre = 0.0

        # build
        grad, pulse, duration, area_grad = cls.build_pulse_grad_shapes(
            pulse=pulse_from_pypsi, grad_amp_slice_select=params.sequence.gradient_refocus,
            duration_pulse_slice_select_us=params.sequence.duration_refocus,
            grad_amp_post=params.sequence.gradient_crush + gradient_read_pre_phase,
            duration_post_us=params.sequence.duration_crush,
            grad_amp_pre=gradient_slice_pre,
            duration_pre_us=params.sequence.duration_crush,
            grad_amp_verse_lobe=params.sequence.gradient_refocus_verse_lobes,
            duration_verse_lobe_us=params.sequence.duration_refocus_verse_lobes
        )
        # assign vars
        grad_pulse = cls(
            pulse_type="Refocus", pulse_number=refocus_pulse_number,
            num_sampling_points=pulse_from_pypsi.shape[-1],
            dt_sampling_steps_us=params.sequence.duration_refocus / pulse_from_pypsi.shape[-1],
            duration_us=params.sequence.duration_refocus
        )
        grad_pulse.assign_data(grad=grad, pulse_cplx=pulse)
        return grad_pulse

    @staticmethod
    def _set_pulse(params: options.SimulationParameters, duration_us: float, excitation: bool):
        log_module.debug(f"\t RF")
        # check rf and given sim details
        if np.abs(params.pulse.get_duration_us(excitation=excitation) - duration_us) > 1e-5:
            params.pulse.resample_to_duration(duration_in_us=int(duration_us),
                                              excitation=excitation)
        # resample pulse to given dt in us for more efficient computation
        if np.abs(
                params.pulse.get_dt_sampling_in_us(excitation=excitation) - params.config.resample_pulse_to_dt_us
        ) > 1.0:
            params.pulse.set_shape_on_raster(raster_time_s=params.config.resample_pulse_to_dt_us * 1e-6,
                                             excitation=excitation)
        return params

    @staticmethod
    def build_pulse_grad_shapes(
            pulse: torch.tensor, grad_amp_slice_select: float, duration_pulse_slice_select_us: float,
            grad_amp_post: float, duration_post_us: float,
            duration_pre_us: float = 0.0, grad_amp_pre: float = 0.0,
            duration_verse_lobe_us: float = 0.0, grad_amp_verse_lobe: float = 0.0):
        """ want to build the shapes given slice gradient pre, spoil and slice select and align it to the given pulse"""
        # grad amplitudes are values, pulse is a shape already with complex numbers and
        # distributed across different b1 values -> pulse dim [# b1, # pulse sampling steps]

        # check if we have pre gradient
        if np.abs(grad_amp_pre) < 1e-5:
            duration_pre_us = 0
        duration_pre_us = torch.full(size=(1,), fill_value=duration_pre_us)
        grad_amp_pre = torch.full(size=(1,), fill_value=grad_amp_pre)
        # set number of samplings for pulse
        num_sample_pulse = pulse.shape[1]
        dt_us = duration_pulse_slice_select_us / num_sample_pulse
        # calculate total number of sampling points
        # pre gradient
        num_sample_pre = torch.nan_to_num(torch.div(
            duration_pre_us, dt_us, rounding_mode="trunc"
        )).type(torch.int)
        # post gradient
        num_sample_crush = torch.nan_to_num(torch.div(
            duration_post_us, dt_us, rounding_mode="trunc"
        )).type(torch.int)
        # total number
        num_sample_total = num_sample_pre + num_sample_pulse + num_sample_crush
        # allocate tensors
        grad_amp = torch.zeros(num_sample_total)
        pulse_amp = torch.zeros((pulse.shape[0], num_sample_total), dtype=torch.complex128)
        # ___ fill
        # pre
        grad_amp[:num_sample_pre] = grad_amp_pre
        # slice select, check for verse
        if duration_verse_lobe_us > 1e-3:
            # might have to address pulse - grad delay timing mismatches here
            num_samples_lobe = int(duration_verse_lobe_us / dt_us)
            num_samples_plateau = num_sample_pulse - 2 * num_samples_lobe
            s_pts = np.array([
                0,
                num_samples_lobe,
                num_samples_lobe + num_samples_plateau,
                2 * num_samples_lobe + num_samples_plateau
            ])
            s_vals = np.array([
                grad_amp_verse_lobe, grad_amp_slice_select, grad_amp_slice_select, grad_amp_verse_lobe
            ])
            middle_amp = torch.from_numpy(np.interp(x=np.arange(num_sample_pulse), xp=s_pts, fp=s_vals))
        else:
            middle_amp = grad_amp_slice_select
        grad_amp[num_sample_pre:num_sample_pre + num_sample_pulse] = middle_amp
        grad_amp[num_sample_pre + num_sample_pulse:] = grad_amp_post
        pulse_amp[:, num_sample_pre:num_sample_pre + num_sample_pulse] = pulse
        t_total = num_sample_total * dt_us
        return grad_amp, pulse_amp, t_total, torch.sum(
            grad_amp[num_sample_pre:num_sample_pre + num_sample_pulse]) * dt_us

    # @classmethod
    # def prep_single_grad_pulse(cls, params: options.SimulationParameters = options.SimulationParameters(),
    #                            excitation_flag: bool = True,
    #                            grad_rephase_factor: float = 1.0):
    #     # -- prep pulse
    #     pulse_type: str = 'Excitation'  # just set it
    #     log_module.debug(f'prep pulse {pulse_type}; # {0}')
    #     grad_pulse = cls(pulse_type=pulse_type, pulse_number=0)
    #     # read file
    #     # get duration & grad pulse defaults
    #     gp_details = GPDetails.get_gp_details(params=params, excitation_flag=excitation_flag)
    #     gp_details.grad_crush_rephase *= grad_rephase_factor
    #     if grad_rephase_factor < 1e-3:
    #         gp_details.duration_crush_rephase = 0.0
    #     # read rf
    #     rf = pypsi.Params.pulse.load(gp_details.pypsi_path)
    #     duration_pulse = params.sequence.duration_excitation
    #
    #     if abs(rf.duration_in_us - duration_pulse) > 1e-5:
    #         # resample pulse
    #         rf.resample_to_duration(duration_in_us=int(duration_pulse))
    #
    #     pulse = torch.from_numpy(rf.amplitude) * torch.exp(torch.from_numpy(1j * rf.phase))
    #     # calculate and normalize
    #     pulse_from_pypsi = functions.pulse_calibration_integral(
    #         pulse=pulse,
    #         delta_t_us=rf.get_dt_sampling_in_us(),
    #         pulse_number=0,
    #         sim_params=params,
    #         excitation=True)
    #
    #     # build verse pulse gradient
    #     grad, pulse, duration, area_grad = cls.build_pulse_grad_shapes(
    #         gp_details=gp_details,
    #         pulse=pulse_from_pypsi,
    #         duration_pre_us=0.0,
    #         grad_amp_pre=0.0
    #     )
    #
    #     # assign vars
    #     grad_pulse.num_sampling_points = rf.num_samples
    #     grad_pulse.dt_sampling_steps = rf.get_dt_sampling_in_us()
    #     grad_pulse.data_grad = grad
    #     grad_pulse.data_pulse_x = pulse.real
    #     grad_pulse.data_pulse_y = pulse.imag
    #     grad_pulse.duration = rf.duration_in_us
    #
    #     grad_pulse._set_float32()
    #     return grad_pulse

    @classmethod
    def prep_acquisition(cls, params: options.SimulationParameters = options.SimulationParameters()):
        log_module.debug("prep acquisition")
        dt_sampling_steps = params.sequence.duration_acquisition / params.settings.acquisition_number

        grad_pulse = cls(pulse_type='Acquisition', pulse_number=0, num_sampling_points=1,
                         dt_sampling_steps_us=dt_sampling_steps)
        # assign data
        grad_pulse.data_grad = torch.linspace(
            params.sequence.gradient_acquisition,
            params.sequence.gradient_acquisition,
            1)
        # need to cast to pulse data dim [b1s, num_steps]
        grad_pulse.data_pulse_x = torch.linspace(0, 0, 1)[None, :]
        grad_pulse.data_pulse_y = torch.linspace(0, 0, 1)[None, :]
        grad_pulse.duration = params.sequence.duration_acquisition
        grad_pulse._set_float32()
        return grad_pulse

    def assign_data(self, grad: torch.tensor, pulse_cplx: torch.tensor):
        self.data_grad = grad
        self.data_pulse_x = torch.real(pulse_cplx)
        self.data_pulse_y = torch.imag(pulse_cplx)

        self._set_float32()

    def plot(self, sim_data: options.SimulationData, fig_path: str | plib.Path):
        plotting.plot_grad_pulse(
            px=self.data_pulse_x, py=self.data_pulse_y,
            g=self.data_grad, b1_vals=sim_data.b1_vals,
            out_path=fig_path,
            name=f"{self.pulse_type}-{self.pulse_number}"
        )


class Timing:
    def __init__(self, value_us: float):
        self.value_us: torch.tensor = torch.tensor(value_us)

        # sanity check
        if value_us < 1e-12:
            err = f"negative delay set"
            log_module.error(err)
            raise ValueError(err)

    def get_value_s(self):
        return 1e-6 * self.value_us

    def set_device(self, device):
        self.value_us.to(device)


class SequenceTimings:
    def __init__(self):
        self.timings: list = []
        self.num_registered_times: int = len(self.timings)
        self._name_register: dict = {}

    def register_timing(self, value_us: float, name: str):
        self._name_register[name] = len(self._name_register)
        self.timings.append(Timing(value_us=value_us))
        self.num_registered_times = len(self.timings)

    def get_timing_s(self, identifier: str | int):
        if isinstance(identifier, str):
            idx = self._name_register[identifier]
        else:
            idx = identifier
        return self.timings[idx].get_value_s()

    def set_device(self, device):
        for timing in self.timings:
            timing.set_device(device=device)

   # @classmethod
   #  def build_fill_timing_se(cls, params: options.SimulationParameters = options.SimulationParameters()):
   #      """
   #      Create a timing scheme: save time in [us] in array[2] -> [0] before pulse, [1] after pulse.
   #      For SE sequence
   #      :return: timing array
   #      """
   #      # all in [us]
   #      time_pre_pulse = torch.zeros(1)
   #      time_post_pulse = torch.zeros(1)
   #      # after excitation - before refocusing (check for prephaser):
   #      time_pre_pulse[0] = 1000 * params.sequence.esp / 2 - (
   #              params.sequence.duration_excitation / 2 + params.sequence.duration_excitation_rephase
   #              + params.sequence.duration_refocus / 2
   #      )
   #      # refocusing pulse...
   #      # after refocusing
   #      time_post_pulse[0] = 1000 * params.sequence.esp / 2 - (
   #              params.sequence.duration_refocus / 2 + params.sequence.duration_crush +
   #              params.sequence.duration_acquisition / 2
   #      )
   #      return cls(time_pre_pulse=time_pre_pulse, time_post_pulse=time_post_pulse)
   #
   #  def set_device(self, device: torch.device):
   #      self.time_post_pulse = self.time_post_pulse.to(device)
   #      self.time_pre_pulse = self.time_pre_pulse.to(device)
