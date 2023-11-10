import logging
import pickle
import typing
from pypsi.parameters import EmcParameters
from emc_torch import options
import numpy as np
import pandas as pd
import pathlib as plib
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mpc
import plotly.express as px
from plotly.express.colors import sample_colorscale
import plotly.subplots as psub
import plotly.graph_objects as go

plt.style.use('ggplot')
log_module = logging.getLogger(__name__)


class DB:
    def __init__(self, pd_dataframe: pd.DataFrame = pd.DataFrame(),
                 sequence_config: EmcParameters = EmcParameters(), name: str = "db_"):
        # define structure of pandas df
        self.indices: list = ["emc_mag", "emc_phase", "t2", "t1", "b1"]
        # check indices
        for ind in self.indices:
            if not ind in pd_dataframe.columns:
                err = f"db structure not given. Index {ind} not found. " \
                      f"Make sure these indices are columns in the dataframe: {self.get_indexes()};" \
                      f"\nIndices found in db: {pd_dataframe.columns}"
                log_module.error(err)
                raise ValueError(err)
        self.pd_dataframe: pd.DataFrame = pd_dataframe
        self.seq_params: EmcParameters = sequence_config
        self.np_mag_array: np.ndarray = np.array([*pd_dataframe.emc_mag.to_numpy()])
        self.np_phase_array: np.ndarray = np.array([*pd_dataframe.emc_phase.to_numpy()])
        self.etl: int = self.np_mag_array.shape[-1]
        # extract only name in case filename given
        name = plib.Path(name).absolute()
        name = name.stem
        self.name: str = name.__str__()

        # normalize
        self.normalize()

    def get_indexes(self):
        return self.indices

    def get_t2_b1_values(self) -> (np.ndarray, np.ndarray):
        return np.unique(self.pd_dataframe.t2), np.unique(self.pd_dataframe.b1)

    def plot(self,
             out_path: plib.Path | str, name: str = "",
             t1_range_s: tuple = None, t2_range_ms: tuple = (20, 50), b1_range: tuple = (0.5, 1.2)):
        if name:
            name = f"_{name}"
        # select range
        df = self.pd_dataframe
        df["t2"] = 1e3 * df["t2"]
        df["t2"] = df["t2"].round(2)
        df["b1"] = df["b1"].round(2)
        df["echo"] = df["echo"] + 1
        if t2_range_ms is not None:
            df = df[t2_range_ms[0] < df["t2"]]
            df = df[df["t2"] < t2_range_ms[1]]
        if t1_range_s is not None:
            df = df[t1_range_s[0] < df["t1"]]
            df = df[df["t1"] < t1_range_s[1]]
        if b1_range is not None:
            df = df[b1_range[0] < df["b1"]]
            df = df[df["b1"] < b1_range[1]]
        # for now we only take one t1 value
        df = df[df["t1"] == df["t1"].unique()[0]].drop(columns=["t1"]).drop(columns="index").reset_index(drop=True)
        # setup colorscales to use
        x = np.linspace(0.2, 1, len(df["t2"].unique()))
        c_scales = ["Purples", "Oranges", "Greens", "Reds", "Blues"]
        echo_ax = df["echo"].to_numpy()
        # setup subplots
        num_plot_b1s = len(df["b1"].unique())
        titles = ["Magnitude", "Phase"]
        fig = psub.make_subplots(
            2, 1, shared_xaxes=True, subplot_titles=titles
        )
        # edit axis labels
        fig['layout']['xaxis2']['title'] = 'Echo Number'
        fig['layout']['yaxis']['title'] = 'Signal [a.u.]'
        fig['layout']['yaxis2']['title'] = 'Phase [rad]'

        for b1_idx in range(num_plot_b1s):
            c_tmp = sample_colorscale(c_scales[b1_idx], list(x))
            temp_df = df[df["b1"] == df["b1"].unique()[b1_idx]].reset_index(drop=True)
            for t2_idx in range(len(temp_df["t2"].unique())):
                t2 = temp_df["t2"].unique()[t2_idx]
                c = c_tmp[t2_idx]

                mag = temp_df[temp_df["t2"] == t2]["emc_mag"].to_numpy()
                mag /= np.abs(np.max(mag))
                fig.add_trace(
                    go.Scatter(
                        x=echo_ax, y=mag, marker_color=c, showlegend=False
                    ),
                    1, 1
                )

                phase = temp_df[temp_df["t2"] == t2]["emc_phase"].to_numpy()
                fig.add_trace(
                    go.Scatter(
                        x=echo_ax, y=phase, marker_color=c, showlegend=False
                    ),
                    2, 1
                )
            # add colorbar
            colorbar_trace = go.Scatter(
                x=[None], y=[None], mode='markers',
                showlegend=False,
                marker=dict(
                    colorscale=c_scales[b1_idx], showscale=True,
                    cmin=t2_range_ms[0], cmax=t2_range_ms[1],
                    colorbar=dict(
                        title=f"B1: {df['b1'].unique()[b1_idx]}",
                        x=1.02 + 0.05 * b1_idx
                    )
                )
            )
            fig.add_trace(colorbar_trace, 1, 1)

        # colorbar labels
        fig.add_annotation(
            xref="x domain", yref="y domain", x=1.005, y=-0.5, showarrow=False,
            text="T2 [ms]", row=1, col=1, textangle=-90, font=dict(size=14)
        )
        # df_mag = df[["t2", "b1", "emc_mag", "echo"]].rename(columns={"emc_mag": "data"})
        # df_mag = pd.concat((df_mag.reset_index(), pd.Series(["emc_mag"] * len(df_mag), name="label")), axis=1)
        # df_mag["data"] = df_mag["data"] / df_mag["data"].abs().max()
        # df_phase = df[["t2", "b1", "emc_phase", "echo"]].rename(columns={"emc_phase": "data"})
        # df_phase = pd.concat((df_phase.reset_index(), pd.Series(["emc_phase"] * len(df_mag), name="label")), axis=1)
        # df_phase["data"] = df_phase["data"] / np.pi
        # df_plot = pd.concat((df_mag, df_phase))
        # fig = px.line(df_plot, x="echo", y="data", color="t2", markers=True, facet_col="b1", facet_row="label",
        #               labels={
        #                   "echo": "Echo Number",
        #                   "data": "Echo Magnitude | phase [A.U. | pi]",
        #                   "t2": "T2 [ms]",
        #                   "b1": "B1"
        #               })
        # fig.update_yaxes(range=[-1, 1])

        out_path = plib.Path(out_path).absolute()
        fig_file = out_path.joinpath(f"emc_db{name}").with_suffix(".html")
        log_module.info(f"writing file: {fig_file.as_posix()}")
        fig.write_html(fig_file.as_posix())

    def plot_mpl(self, t2_range_ms: tuple = (10.0, 40.0), b1_range: tuple = (0.6, 1.2), save: str = ""):
        log_module.info("plotting")
        t2_range_s = 1e-3 * np.array(t2_range_ms)
        df_selection = self.pd_dataframe[self.pd_dataframe.t2.between(t2_range_s[0], t2_range_s[1], inclusive='both')]
        df_selection = df_selection[df_selection.b1.between(b1_range[0], b1_range[1], inclusive='both')]
        t2s = np.unique(df_selection.t2)
        b1s = np.unique(df_selection.b1)

        x_ax = np.arange(1, self.etl + 1)

        if b1s.shape[0] > 8:
            b1s = b1s[::2]
        if b1s.shape[0] > 4:
            b1s = b1s[:4]

        curves = np.zeros((t2s.shape[0], b1s.shape[0], self.etl))
        c_range = np.linspace(0.25, 1.0, t2s.shape[0])

        cmaps = [cm.get_cmap('Purples'), cm.get_cmap('Greens'), cm.get_cmap('Oranges'), cm.get_cmap('Reds')]
        colors = [cmaps[k](c_range) for k in range(b1s.shape[0])]

        for t2_idx in range(t2s.shape[0]):
            for b1_idx in range(b1s.shape[0]):
                curve = df_selection.emc_signal[
                    (df_selection.t2 == t2s[t2_idx]) & (df_selection.b1 == b1s[b1_idx])
                    ].to_numpy()[0]
                curves[t2_idx, b1_idx] = np.divide(curve, np.linalg.norm(curve))

        fig = plt.figure(figsize=(14, 6))
        wr = np.ones(len(cmaps) + 1)
        wr[0] = 20

        gs = fig.add_gridspec(1, 1 + len(cmaps), width_ratios=wr, wspace=0.1)
        ax = fig.add_subplot(gs[0])
        ax.set_xlabel(f"echo #")
        ax.set_ylabel(f"$l_2$ normalized intensity [A.U.]")
        ax.set_yticklabels([])

        for b in range(curves.shape[1]):
            ax.hlines(0.2 * (b + 1), 0, x_ax[-1], color=colors[b][-int(t2s.shape[0] / 3)],
                      linestyle='dotted', zorder=curves.shape[1] - b + 1)
            for a in range(curves.shape[0]):
                ax.plot(x_ax, 0.2 * (b + 1) + curves[a, b], color=colors[b][a], zorder=curves.shape[1] - b + 1)

        norm = mpc.Normalize(vmin=t2_range_ms[0], vmax=t2_range_ms[1])
        ticks = [[], None]
        titles = [f"$B_1$: {b1s[0]:.1f} \t", *[f"{b1s[k]:.1f}" for k in np.arange(1, b1s.shape[0])]]
        cb = NotImplemented
        for k in range(len(cmaps)):
            cax = fig.add_subplot(gs[1 + k])
            cax.grid(False)
            if k < len(cmaps) - 1:
                cb = fig.colorbar(cm.ScalarMappable(norm=norm, cmap=cmaps[k]), cax=cax, ticks=ticks[0])
            else:
                cb = fig.colorbar(cm.ScalarMappable(norm=norm, cmap=cmaps[k]), cax=cax)
            cax.set_title(titles[k])
        cb.set_label(f"$T_2$ [ms]")
        if save:
            save_path = plib.Path(save).absolute()
            if not save_path.suffixes:
                save_path = save_path.joinpath(f"{self.name}_plot.png")
            if ".png" not in save_path.suffixes:
                log_module.info(f"plot saved as .png image. suffix adapted!")
                save_path = save_path.with_suffix(".png")
            save_path.parent.mkdir(exist_ok=True, parents=True)
            plt.savefig(save_path, bbox_inches='tight', transparent=True)
        plt.show()

    def save(self, path: typing.Union[str, plib.Path]):
        path = plib.Path(path).absolute()
        if not path.suffixes:
            # given a path not a file
            path = path.joinpath(f"{self.name}_database_file.pkl")
        if ".pkl" not in path.suffixes:
            # given wrong filending
            log_module.info("filename saved as .pkl, adopting suffix.")
            path = path.with_suffix('.pkl')
        # mkdir ifn existent
        path.parent.mkdir(exist_ok=True, parents=True)

        log_module.info(f"writing file {path}")

        with open(path, "wb") as p_file:
            pickle.dump(self, p_file)

    @classmethod
    def load(cls, path: typing.Union[str, plib.Path]):
        path = plib.Path(path).absolute()
        if ".pkl" not in path.suffixes:
            # given wrong filending
            log_module.info("filename not .pkl, try adopting suffix.")
            path = path.with_suffix('.pkl')
        if not path.is_file():
            # given a path not a file
            err = f"{path.__str__()} not a file"
            log_module.error(err)
            raise ValueError(err)
        with open(path, "rb") as p_file:
            db = pickle.load(p_file)
        return db

    def normalize(self):
        arr = self.np_mag_array
        norm = np.linalg.norm(arr, axis=-1, keepdims=True)
        self.np_mag_array = np.divide(arr, norm, where=norm > 1e-12, out=np.zeros_like(arr))

        for k in range(len(self.pd_dataframe)):
            self.pd_dataframe.at[k, "emc_mag"] = self.np_mag_array[k]

    def get_numpy_array(self) -> (np.ndarray, np.ndarray):
        self.normalize()
        return self.np_mag_array, self.np_phase_array

    def append_zeros(self):
        # want 0 lines for fitting noise
        # b1s = self.pd_dataframe.b1.unique().astype(float)
        # t1s = self.pd_dataframe.t1.unique().astype(float)
        # ds = self.pd_dataframe.d.unique().astype(float)
        # for b1, t1, d in [(b1_val, t1_val, d_val) for b1_val in b1s for t1_val in t1s for d_val in ds]:
        #     # when normalizing 0 curves will be left unchanged. Data curves are unlikely 0
        #     temp_row = self.pd_dataframe.iloc[0].copy()
        #     temp_row.emc_signal = np.full(len(temp_row.emc_signal), 1e-5)
        #     temp_row.t2 = 1e-3
        #     temp_row.b1 = b1
        #     temp_row.t1 = t1
        #     temp_row.d = d
        #     self.pd_dataframe.loc[len(self.pd_dataframe.index)] = temp_row
        #     # still append 0 curves that wont get scaled -> useful if normalization leaves signal curve flat
        #     temp_row = self.pd_dataframe.iloc[0].copy()
        #     temp_row.emc_signal = np.zeros([len(temp_row.emc_signal)])
        #     temp_row.t2 = 0.0
        #     temp_row.b1 = b1
        #     temp_row.t1 = t1
        #     temp_row.d = d
        #     self.pd_dataframe.loc[len(self.pd_dataframe.index)] = temp_row
        # self.pd_dataframe = self.pd_dataframe.reset_index(drop=True)
        # self.np_array = np.array([*self.pd_dataframe.emc_signal.to_numpy()])
        # self.normalize()
        # ToDo: needs to be reworked
        pass

    @classmethod
    def build_from_sim_data(cls, sim_params: EmcParameters, sim_data: options.SimulationData):
        d = {}
        index = 0
        for idx_t1 in range(sim_data.t1_vals.shape[0]):
            for idx_t2 in range(sim_data.t2_vals.shape[0]):
                for idx_b1 in range(sim_data.b1_vals.shape[0]):
                    for idx_echo in range(sim_data.emc_signal_mag.shape[-1]):
                        td = {
                            "index": index,
                            "t1": sim_data.t1_vals[idx_t1].clone().detach().cpu().item(),
                            "t2": sim_data.t2_vals[idx_t2].clone().detach().cpu().item(),
                            "b1": sim_data.b1_vals[idx_b1].clone().detach().cpu().item(),
                            "echo": idx_echo,
                            "emc_mag": sim_data.emc_signal_mag[
                                idx_t1, idx_t2, idx_b1, idx_echo].clone().detach().cpu().item(),
                            "emc_phase": sim_data.emc_signal_phase[
                                idx_t1, idx_t2, idx_b1, idx_echo].clone().detach().cpu().item()
                        }
                        d.__setitem__(index, td)
                        index += 1
        db_pd = pd.DataFrame(d).T
        return cls(pd_dataframe=db_pd, sequence_config=sim_params)


if __name__ == '__main__':
    dl = DB.load("test/test_db_database_file.pkl")
    dl.plot()
