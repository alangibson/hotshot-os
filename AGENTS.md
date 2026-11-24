

- Target platform is Raspberry Pi 4
- Connect to Raspberry Pi computer over key-authenticated ssh at operator@raspberrypi.local
- Use `ssh -F /dev/null` instead of just `ssh` to get around sandbox restriction
- Be sure to configure GPIO pins as needed by the requirement
- Whenever you are done, copy this directory to operator@raspberrypi.local:/home/operator/hotshot-os/
- Use pinctrl instead of raspi-gpio
