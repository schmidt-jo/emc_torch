from emc_sim import options, simulations
import logging
logging.getLogger('simple_parsing').setLevel(logging.WARNING)


def main(sim_params: options.SimulationParameters):
    sim_params.config.display()

    # simulate
    db, sim_params, sim_data = simulations.simulate(sim_params=sim_params)


if __name__ == '__main__':

    logging.basicConfig(format='%(asctime)s %(levelname)s :: %(name)s --  %(message)s',
                        datefmt='%I:%M:%S', level=logging.INFO)
    logging.info("__________________________________________________________")
    logging.info("__________________ EMC torch simulation __________________")
    logging.info("__________________________________________________________")

    parser, prog_args = options.create_cli()

    opts = options.SimulationParameters.from_cli(prog_args)
    # set logging level after possible config file read
    if opts.config.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        main(sim_params=opts)

    except Exception as e:
        logging.exception(e)
        parser.print_usage()
