# Russound-RIO-daemon
The purpose of riod.py to permanelty run as a daemon on a unix hosts, e.g. raspberry and provide the status of a Russound device MCA-C3, MCA-C5 or MCA-88.
It always able to provide the current configuration via built in Web Service and could send update to specific hosts via TCP and UPD and provide the status of a Russound device MCA-C3, MCA-C5 or MCA-88.
It has been only tested with python3. Location of riod.ini could be either script dir, /etc or /usr/local/etc
The ini file is key, to configure russounf target, Radio channels, as well as any outbank udp or tcp connections
<br>
It allows to control the russound as well:


Example: http://127.0.0.1:8080/cmd?action=on&zone=1&source=2

Webbrowser works ok, if you would like to use curl: curl "http://127.0.0.1:8080/cmd?action=on&zone=1&source=2"

action:<br>
	On - zone power on : zone, source<br>
	play - play a source and specific channel : zone, source, channel<br>
	Off - zone power off : zone<br>
	source - set source of zone : zone, source<br>
	volume - set volume of zone : zone, volume<br>
	bass - set bass of zone : zone, bass<br>
	treble - set treble of zone : zone, treble<br>
	balance - set bass of zone : zone, balance<br>
	turnOnVolume - set turnOnVolume to volume for zone<br>
<br>
Parameter:<br>
zone: Zone number e.g. 1 or 1,4,5 etc...<br>
controller: Controller number e.g. 1 ( default is 1)<br>
volume: Volume for announcements and for fade-in (1..50)<br>
source: set zone to source number<br>
bass: bass value to be send -10 to 10<br>
treble: treble to be send -10 to 10<br>
balance: Balance -10 to 10<br>
channel: Radio Channel, defined in riod.ini, to be changed to

The easiest way to run the script at startup:
1. cp systemd/riod.service /lib/systemd/system/riod.service
2. sudo systemctl daemon-reload
3. sudo systemctl enable riod.service
4. sudo systemctl start riod.service

