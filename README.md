# Russound-RIO-daemon
The purpose of riod.py to permanelty run as a daemon on a unix hosts, e.g. raspberry and provide the status of a Russound device MCA-C3, MCA-C5 or MCA-88.
It always able to provide the current configuration via built in Web Service and could send update to specific hosts via TCP and UPD and provide the status of a Russound device MCA-C3, MCA-C5 or MCA-88
It allows to control the russound as well:

Example: http://<IP Webserver>:<port>/cmd?action=on&zone=1&source=2

action:
	On - zone power on : zone, source
	Off - zone power off : zone
	source - set source of zone : zone, source
	volume - set volume of zone : zone, volume
	bass - set bass of zone : zone, bass
	treble - set treble of zone : zone, treble
	balance - set bass of zone : zone, balance
	turnOnVolume - set turnOnVolume to volume for zone

Parameter:
zone: Zone number e.g. 1 or 1,4,5 etc...
controller: Controller number e.g. 1 ( default is 1)
volume: Volume for announcements and for fade-in (1..50)
source: set zone to source number
bass: bass value to be send -10 to 10
treble: treble to be send -10 to 10
balance: Balance -10 to 10

