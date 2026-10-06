#!/bin/bash
# Install gridlink on a Raspberry Pi (Raspberry Pi OS Bookworm or later).
# Run from the unpacked gridlink folder:  bash install.sh
set -e
DEST=/home/$USER/gridlink
mkdir -p "$DEST" ~/.config/gridlink ~/gridlink/work ~/gridlink/memories ~/gridlink/sessions
cp -r gridlink PROTOCOL.md README.md config.example.toml gridlink.service "$DEST"/ 2>/dev/null || true
cd "$DEST"
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install anthropic pyserial pillow
[ -f ~/.config/gridlink/config.toml ] || cp config.example.toml ~/.config/gridlink/config.toml
sudo usermod -a -G dialout "$USER"          # serial port access
if [ ! -f ~/.config/gridlink/api_key ]; then
    echo
    echo "Put your Anthropic Console API key in ~/.config/gridlink/api_key"
    echo "(one line), then:  chmod 600 ~/.config/gridlink/api_key"
fi
sed "s#/home/pi#/home/$USER#g; s#User=pi#User=$USER#" gridlink.service | sudo tee /etc/systemd/system/gridlink.service >/dev/null
sudo systemctl daemon-reload
echo
echo "Try it in the terminal first:   cd $DEST && venv/bin/python -m gridlink --console"
echo "Then start the service:         sudo systemctl enable --now gridlink"
echo "Logs:                           journalctl -u gridlink -f"
