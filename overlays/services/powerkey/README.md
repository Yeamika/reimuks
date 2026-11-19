# Power key

Shared power-key policy, event service, and build entry point. Profiles without a
board-specific daemon use logind's poweroff default. A profile that enables
`reimuks-powerkey.service` supplies `/etc/default/reimuks-powerkey` with its input
device name and action settings.

The source and press state machine are board-independent; display paths, blank values,
input names, press timing, and short/long actions are runtime configuration. Supported
actions are `display-toggle`, `poweroff`, `suspend`, and `ignore`. The input device is
grabbed only while the service is active.
