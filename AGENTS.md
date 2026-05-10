

- Target platform is Raspberry Pi 4
- Connect to Raspberry Pi computer over key-authenticated ssh at operator@raspberrypi.local
- Use `ssh -F /dev/null` instead of just `ssh` to get around sandbox restriction
- Be sure to configure GPIO pins as needed by the requirement
- Whenever you are done, copy the file you modified into operator@raspberrypi.local:/home/operator/test/
- Use pinctrl instead of raspi-gpio