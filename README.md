# Hotshot OS

## Installation

### Burn OS image

Just burn Raspberry Pi OS to SD card with Raspberry Pi Imager. 

then copy this directory to `/home/operator/hotshot-os` on the Raspberry Pi.

### On Raspberry Pi OS

#### Install realtime kernel

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y linux-image-rpi-v8-rt
echo 'kernel=kernel8_rt.img' | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

After reboot, confirm that RT kernel is running

```bash
uname -a | grep PREEMPT_RT
```

#### Install libgpiod

```bash
sudo apt install libgpiod-dev gpiod
```

#### Install boot overlays and config

```bash
sudo apt install device-tree-compiler
cd /home/operator/hotshot-os
./install.sh
sudo reboot
```

`install.sh` installs the build dependencies, builds and installs `spi0-7cs.dts` and `mcp23s17-spi0-6.dts`, installs `config.txt`, patches and rebuilds the MCP23S17 SPI kernel module, and refreshes the boot initramfs. GPIO0 is used as the CS6 chip-select pin for the MCP23S17 on `spi0.6`.

After reboot, confirm the MCP23S17 is bound:

```bash
dmesg | grep -Ei 'mcp23|spi0.6|deferred'
gpioinfo
```

The kernel may log `Fixed dependency cycle(s)` for the MCP23S17 `pullups` pinctrl node. That line is expected when the MCP23S17 GPIO chip and its pinctrl pull-up configuration reference each other. The failure cases to investigate are `deferred probe pending`, `can't add GPIO chip`, or `missing spi-present-mask`.

#### Configure RTC

```bash
sudo apt install -y util-linux-extra
sudo tee -a /boot/firmware/config.txt <<"EOF"
dtparam=i2c_arm=on
dtoverlay=i2c-rtc,mcp7940x
EOF
sudo reboot
```

After reboot, confirm RTC is working

```bash
ls /dev/i2c-1
ls /dev/rtc*
dmesg | grep -i 'rtc-'
sudo i2cdetect -y 1
```

Set time on RTC from local clock

```bash
sudo hwclock --systohc --utc
sudo hwclock --show --utc --noadjfile
```

Make sure RTC time is used by local clock on reboot

```bash
sudo tee /usr/local/sbin/rtc-to-system-clock >/dev/null <<'EOF'
#!/bin/sh

for i in $(seq 1 180); do
    epoch=$(cat /sys/class/rtc/rtc0/since_epoch 2>/dev/null) || {
        sleep 1
        continue
    }

    case "$epoch" in
        ''|*[!0-9]*) sleep 1; continue ;;
    esac

    # Reject systemd built-in epoch / obviously stale times.
    if [ "$epoch" -gt 1760000000 ]; then
        date -u -s "@$epoch"
        exit 0
    fi

    sleep 1
done

exit 1
EOF

sudo chmod 755 /usr/local/sbin/rtc-to-system-clock
```

```bash
sudo tee /etc/udev/rules.d/85-hwclock.rules >/dev/null <<'EOF'
ACTION=="add", SUBSYSTEM=="rtc", KERNEL=="rtc0", TAG+="systemd", ENV{SYSTEMD_WANTS}+="rtc-hctosys-late.service"
EOF
```

```bash
sudo tee /etc/systemd/system/rtc-hctosys-late.service >/dev/null <<'EOF'
[Unit]
Description=Set system clock from RTC after rtc0 is readable
After=dev-rtc0.device
Wants=dev-rtc0.device

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/rtc-to-system-clock
EOF
```

```bash
sudo systemctl daemon-reload
sudo udevadm control --reload-rules
sudo reboot
```

#### Install LinuxCNC

```bash
sudo apt install -y  linuxcnc-uspace linuxcnc-uspace-dev
```

### References

https://forums.raspberrypi.com/viewtopic.php?t=388298
https://forums.raspberrypi.com/viewtopic.php?t=396623
https://forum.linuxcnc.org/9-installing-linuxcnc/55048-raspberry-pi-os-preempt-rt-6-13-kernel-cookbook
