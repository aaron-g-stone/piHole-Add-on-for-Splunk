import import_declare_test

import sys

from splunklib import modularinput as smi
from pihole_stats_summary_helper import stream_events, validate_input


class PIHOLE_STATS_SUMMARY(smi.Script):
    def __init__(self):
        super(PIHOLE_STATS_SUMMARY, self).__init__()

    def get_scheme(self):
        scheme = smi.Scheme('pihole_stats_summary')
        scheme.description = 'Pi-hole Stats Summary (metrics)'
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        scheme.add_argument(
            smi.Argument(
                'name',
                title='Name',
                description='Name',
                required_on_create=True
            )
        )
        scheme.add_argument(
            smi.Argument(
                'account',
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                'metrics_to_ingest',
                required_on_create=False,
            )
        )
        return scheme

    def validate_input(self, definition: smi.ValidationDefinition):
        return validate_input(definition)

    def stream_events(self, inputs: smi.InputDefinition, ew: smi.EventWriter):
        return stream_events(inputs, ew)


if __name__ == '__main__':
    exit_code = PIHOLE_STATS_SUMMARY().run(sys.argv)
    sys.exit(exit_code)