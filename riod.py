#!/usr/bin/python3
# -*- coding: iso-8859-15 -*-
#
# This is the config file for riod.py script
# The purpose of riod.py to permanelty run as a daemon on a unix hosts, e.g. raspberry
# and provide the status of a Russound device MCA-C3, MCA-C5 or MCA-88
# Location of riod.ini could be: current dir, /etc or /usr/local/etc
#
# V1.1   02.02.2019 - First release
# V1.2   28.02.2019 - Added activeZone to Source array
# V1.3   09.03.2019 - Improve Config read
# V1.4   09.03.2019 - Send command to russound
# V1.4.1 13.03.2019 - Bugfix ini file location
# V1.5   19.03.2019 - Add ssl support
# V1.5.1 07.04.2019 - Change Status output
# V1.6   04.05.2019 - Improved error handling @webservice
# V1.7   09.10.2019 - Relative volume change cmd
# V1.7.1 13.10.2019 - Fix Broken Pipe connection error
# V1.7.2 13.10.2019 - Fix Bug ignoring step 1
# V1.7.3 23.02.2020 - Fix Bug send2Network
# V1.7.4 29.02.2020 - Add cmd volup and voldown
# V1.7.5 19.04.2020 - Add cmd toggle
# V1.8 	 24.04.2020 - Implement mqtt protocol for status updates and Cmd
# V1.9 	 27.04.2020 - Translate RDS from IEC62106 to ISO-8859-15

import configparser
import datetime
import errno
import json
import optparse
import os
import paho.mqtt.client as mqtt
import re
import socket
import ssl
import string
import struct
import sys
import syslog
import threading
import time

from collections import defaultdict

class recursivedefaultdict(defaultdict):
    def __init__(self):
        self.default_factory = type(self) 
		
ZoneConfig=recursivedefaultdict()
SourceConfig=defaultdict(dict)
ZoneCount=defaultdict(dict)
ControllerType=defaultdict(dict)

MQTT_TOPIC_DEFAULT="/riod"
MQTT_TOPIC_DATA="/Data"
MQTT_TOPIC_ACK="/Ack"
MQTT_TOPIC_CMD="/Cmd"
MQTT_TOPIC_GET="/Get"
MQTT_TOPIC_SET="/Set"

#//// Init section ////
debugLevel=0
debugTarget=0
debugHex=0
ConvertErrorStr=""
ConvertErrorHex=""
ConvertErrorDate=datetime.datetime(1970,1,1)
ConnectErrorDate=ConvertErrorDate
LastReadDateTime=datetime.datetime.now()
TimebetweenRead=LastReadDateTime-LastReadDateTime
MaxTimeReadDiff=TimebetweenRead
MaxTimeReadDiffDate=LastReadDateTime


# Convert Umlaut from according to IEC 62106 Annex E table 1 translate to ISO_8859-15
# https://de.wikipedia.org/wiki/ISO_8859-15

#	          ö   ä   ü Grad  ß   $   Ä   Ö   Ü   €   ©
IEC_map = b'\x97\x91\x99\xbb\x8d\xab\xd1\xd7\xd9\xa9\xa2'
ISO_map = b'\xf6\xe4\xfc\xb0\xdf\x24\xc4\xd6\xdc\xa4\xa9'

transtab =  bytes.maketrans(IEC_map, ISO_map)


# Convert a string to Hex - String
def str2hex(str):

	hexstr = ""

	hexstr = ''.join([hex(ord(i)) for i in str]);

	return hexstr

# Print Debug message to syslog or screen
def debugFunction(level, msg):
	global debugHex

	if debugTarget == 1:
		if level <= debugLevel:
			syslog.syslog(msg)

	if debugTarget == 2:
		if level <= debugLevel:
			print(msg)
			if debugHex == 1:
				print(str2hex(msg))
		
# Alle network packages are send via send2Network, either with tcp, udp or mqtt
def send2Network(options, msg, QoS=0): 

	debugFunction(3, "send2Network: " + options + " - Msg: " + msg[0:30])

	res=options.split(':') # tcp:127.0.0.1:5001
	prot=res[0].lower()
	msg=msg.strip()
		
	if msg:
		debugFunction(1, "send2Network: " + msg[0:10] + " with Protocol: " + prot)

		if  prot == "mqtt":
			try:
				topic=res[1]
				if not topic: #Topic defined in ini?
					topic=MQTT_TOPIC_DEFAULT
			except:
				topic=MQTT_TOPIC_DEFAULT

			try:
				mqtt_client.publish(topic, bytes(msg, "utf-8"), QoS)
				if debugHex:
					mqtt_client.publish(topic, str2hex(msg), QoS)

			
			except Exception as e:
				debugFunction(0, "send2Network MQTT:" + str(e))

		else:
			host=res[1]
			port=int(res[2])

			try:
				if prot == "udp":
					s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
					s.sendto(bytes(msg, "utf-8"), (host, port))

				elif  prot == "tcp":
					try:
						s.sendall(bytes(msg, "utf-8"))
					except:
						s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
						s.connect((host, port))

#					s.close

				else:
					debugFunction(2, 'Illegal Protocol ' + msg)
				
			except Exception as err:
					debugFunction(0, "EXCEPTION - send2Network: " + str(err))

	else:
		debugFunction(0, 'Received empty string!')

def set_keepalive(sock, after_idle_sec=10, interval_sec=3, max_fails=3):
	# Set TCP keepalive on an open socket.

	# It activates after 10 second (after_idle_sec) of idleness,
	# then sends a keepalive ping once every 3 seconds (interval_sec),
	# and closes the connection after 5 failed ping (max_fails), or 15 seconds
    # 
	sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
	sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, after_idle_sec)
	sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, interval_sec)
	sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, max_fails)
	debugFunction(1, 'Socket Options defined: Idle (sec)=' + str(after_idle_sec) + \
		', Interval (sec)=' + str(interval_sec) + ', MaxFail=' + str(max_fails))
	
# Connect TCP to Russound device
def connectRussound(host, port):
	global s, lastconnect, DeviceVersion, ZoneConfig, ZoneCount, ControllerType, SourceCount

	connected=False
	while not connected:
		try:
			s = socket.socket( socket.AF_INET, socket.SOCK_STREAM)
			s.connect( (host, port))
			debugFunction(0, 'Socket: ' + str(s))
			connected=True
		except socket.error:
			debugFunction(0, 'error occured, try to wake device using WOL...')
			
			if macAddr:
				#////// try to wake the russound ////////////////////////////
				
				addr_byte = macAddr.split(':')
				hw_addr = struct.pack('BBBBBB', int(addr_byte[0], 16),
					int(addr_byte[1], 16),
					int(addr_byte[2], 16),
					int(addr_byte[3], 16),
					int(addr_byte[4], 16),
					int(addr_byte[5], 16))

				msg = b'\xff' * 6 + hw_addr * 16
				debugFunction(0, 'try to send WOL packet.')
		
				# send magic packet
				dgramSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
				dgramSocket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
				dgramSocket.sendto(msg, ("255.255.255.255", 9))

			debugFunction(0, 'Wait for 60 secs..')
			time.sleep(60)

	s.send('VERSION\r'.encode())
	res = s.recv(1024).decode().split('"')
	DeviceVersion = res[1]
	debugFunction(0, 'Version of device: ' + DeviceVersion)
	
	# Read config for each connected Controller
	for c in controllers: 
		s.send(('GET C[' + str(c) + '].type\r').encode())
		res = s.recv(1024).decode().split('"')
		ControllerType[c] = res[1]
		debugFunction(0, 'Type of device: ' + ControllerType[c])

		# Read zones of a Controller
		ZoneCount[c]=0
		while True:
			s.send(('GET C[' + str(c) + '].Z[' + str(ZoneCount[c]+1) + '].name\r').encode())
			res = s.recv(1024).decode()
			if res[0] == 'S': #Success
				ZoneCount[c] += 1
			else:
				debugFunction(0, "ZoneCount=" + str(ZoneCount[c]))
				break

	# Read Number if Sources
	SourceCount=0
	while True:
		s.send(('GET S[' + str(SourceCount+1) + '].name\r').encode())
		res = s.recv(1024).decode()
		if res[0] == 'S': #Success
			SourceCount += 1
		else:
			debugFunction(0, "SourceCount=" + str(SourceCount))
			break
			
	debugFunction(0, 'WATCH SYSTEM ON')
	s.send('WATCH SYSTEM ON\r'.encode())
	lastconnect=datetime.datetime.now() 
		
	# Enable WATCH for all zones
	for c in controllers:
		for l in range(1, ZoneCount[c]+1):
			try:
				ignorezones.index(l) # Test Zone in ignore list
				debugFunction(1, 'Ignore Zone ' + str(l))
			except:
				s.send(('WATCH C[' + str(c) + '].Z[' + str(l) + '] ON\r').encode())
			
	# Enable WATCH for all sources
	for l in range(1, SourceCount+1):
		try:
			ignoresources.index(l) # Test Source in ignore list
			debugFunction(1, 'Ignore Source ' + str(l))
		except:
			s.send(('WATCH S[' + str(l) + '] ON\r').encode())
	
	# Set TCP timeout to reconnect in case of a network outtage
	set_keepalive(s)
	return s	 

#translate IEC 62106 to ISO_8859-15
def checkCharSet(line):

	global ConvertErrorStr, ConvertErrorHex, ConvertErrorDate

	try:
		rc=line.translate(transtab)
	except Exception as err:
		debugFunction(0, "EXCEPTION - CheckCharSet: " + str(err))

	try:
		line = rc.decode('iso-8859-15') 
	except:
		line = rc.decode('iso-8859-15', 'ignore')
		ConvertErrorHex=''.join(hex(ord(x))[2:] for x in rc)
		debugFunction (0, ConvertErrorHex)
		debugFunction(0, 'Convert Error: ' + rc)
		ConvertErrorStr=rc
		ConvertErrorDate=datetime.datetime.now() 


	return line

def countActiveSources():	
	if bool(SourceConfig):
		try:
			for s in SourceConfig:
				SourceConfig[s]["activeZones"]=0

			for controller in ZoneConfig:
				for zone in ZoneConfig[controller]:
					source=ZoneConfig[controller][zone]["currentSource"]

					if ZoneConfig[controller][zone]["status"] == "ON":
						SourceConfig[source]["activeZones"] +=1
		except Exception as err:
			debugFunction(0, "EXCEPTION - countActiveSource: " + str(err))
	else:
		debugFunction(1, "countActiveSource: SoruceConfig is empty")
	

	
def watchRussound(host, port, remoteTargets):
	global DeviceStatus, LastRead, LastReadDateTime, TimebetweenRead, MaxTimeReadDiff, MaxTimeReadDiffDate

	# Initial connect
	s=connectRussound(host, port);

	# Main loop to read controller updates
	while True:
		try:
			result = s.recv(1024)
			debugFunction(2, 'Read: ' + str (result))														  

			TimebetweenRead=datetime.datetime.now() - LastReadDateTime
			
			if MaxTimeReadDiff < TimebetweenRead:
				MaxTimeReadDiff=TimebetweenRead
				MaxTimeReadDiffDate=datetime.datetime.now()

			LastReadDateTime=datetime.datetime.now() 

			for line in result.split(b'\r\n'): #Split results in different lines
				if len(line) > 0:
					
					line=checkCharSet(line)
			
					LastRead=line
					if line[0] is 'N':
						if re.search(r'N System.status\="(.*)"$', line):  #N System.status="OFF" | N System.status="ON"
							res=re.split(r'N System.status\="(.*)"$', line, 0);
							DeviceStatus=res[1]
							debugFunction(0, "SYSTEM: " + line)
							
						elif re.search(r'N C\[(\d)\]\.Z\[(\d)\]\.(\w+)\="(.*)"$', line):  #N C[1].Z[5].name="Wohnzimmer"
							res=re.split(r'N C\[(\d)\]\.Z\[(\d)\]\.(\w+)\="(.*)"$', line, 0);
							source=ZoneConfig[res[1]][res[2]]["currentSource"]

							debugFunction(2, "ZONE: %s, Attr: %s, Current:%s" % ( res[2],res[3],json.dumps(source)))

							ZoneConfig[res[1]][res[2]][res[3]]=res[4]
							debugFunction(2, "ZONE: " + line)
							
							if "ZoneConfig" in remoteTargets:
								send2Network(remoteTargets["ZoneConfig"], json.dumps(ZoneConfig))

							if res[3] == "status" and res[4] == "OFF":
								ZoneConfig[res[1]][res[2]]["volume"]=ZoneConfig[res[1]][res[2]]["turnOnVolume"]
								debugFunction(0, "ZONE " + res[2] + ": Set Volume to " + ZoneConfig[res[1]][res[2]]["volume"])
							if res[3] == "status" or res[3] == "currentSource": # Change of Sources
								countActiveSources();
							
						elif re.search(r'N S\[(\d)\]\.(\w+)\="(.*)"$', line): #N S[5].type="DMS-3.1 Media Streamer"
							debugFunction(3, "SOURCECONFIG: " + json.dumps(SourceConfig))
							res=re.split(r'N S\[(\d)\]\.(\w+)\="(.*)"$', line, 0);
							SourceConfig[res[1]][res[2]]=res[3]
							debugFunction(2, "SOURCE: " + line)

							if "SourceConfig" in remoteTargets:
								send2Network(remoteTargets["SourceConfig"], json.dumps(SourceConfig))

							if res[2] in remoteTargets:
#								print (res[2] + " found in " + remoteTargets[res[2]])
								send2Network(remoteTargets[res[2]], res[3])
							
						else:
							debugFunction(0, "ERROR: " + line)

		except Exception as err:
			ConnectErrorDate=datetime.datetime.now()
			debugFunction(0, "EXCEPTION - connection to Russound: " + str(err))
			s=connectRussound(host, port)

	s.close()
	
def sendCommand(cmd):
	s.send(cmd.encode())
	debugFunction(0, "sendCommand: " + cmd)

def checkCommand(cmdline):
	global ZoneConfig
	digits = [ "DigitZero", "DigitOne", "DigitTwo", "DigitThree", "DigitFour", "DigitFive",
			"DigitSix", "DigitSeven", "DigitEight", "DigitNine" ]
	
	result=dict(re.findall('(\w+)=([\w.+-]+)&?', cmdline.lower())) # e.g zone=1&source=1&action=0
	debugFunction(1, json.dumps(result))

	try:
		action=result["action"]
		zone=result["zone"]

		try:
			c=result["controller"]
		except:
			c=1

		if action == 'toggle':
			try:
				newStatus = 'Off' if ZoneConfig[str(c)][str(zone)]["status"] == 'ON' else 'On'
				debugFunction(2, 'CheckCommand-toogle: ZoneConfig[' + str(c) + '][' + str(zone) + '["status"]:' \
					+ ZoneConfig[str(c)][str(zone)]["status"] + 'New status will be: ' + newStatus   )
				
				if newStatus == "On":
					try:
						source=result["source"]
						cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!KeyRelease SelectSource ' + source + '\r'
					except:
						cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!ZoneOn\r'
				else:
					cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!ZoneOff\r'

			except Exception as err:
				debugFunction(0, "EXCEPTION - checkCommand, action=toggle: " + str(err))

		elif action == "1" or  action== "on":
			try:
				source=result["source"]
				cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!KeyRelease SelectSource ' + source + '\r'
			except:
				cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!ZoneOn\r'

		elif action == "0" or  action== "off":
			cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!ZoneOff\r'
			
		elif action == "source":
			try:
				source=result["source"]
				cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!KeyRelease SelectSource ' + source + '\r'
			except:
				pass

		elif action == "play":
			try:
				source=result["source"]
				try: 
					frequency=result["channel"]
					try:
						frequency=Channels[frequency]
					except:
						pass
					freq_array = ''.join(i for i in frequency if i not in string.punctuation)
				except:
					pass
				
				for i in freq_array :
					cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!KeyRelease ' + digits[int(i)] + '\r'
					sendCommand(cmd)

				cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!KeyRelease Enter\r'
	
			except Exception as err:
				debugFunction(0, "EXCEPTION - checkCommand: " + str(err))
				return 401

		elif action == "volumeup" or action == "volup":
			cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!KeyPress VolumeUp\r'

		elif action == "volumedown" or action == "voldown":
			cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!KeyPress VolumeDown\r'

		elif action == "volume":
			volume=result["volume"]

			if volume[0]=="+":
				count=int(volume[1:])
				cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!KeyPress VolumeUp\r'

				if count < 20:
					i=1
					while (i < count):
						sendCommand(cmd)
						i+=1

			if volume[0] == "-":
				count=int(volume[1:])
				cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!KeyPress VolumeDown\r'

				if count > 0:
					i=1
					while (i < count):
						sendCommand(cmd)
						i+=1
			else:
				if volume.isdigit():
					cmd='EVENT C[' + str(c) + '].Z[' + zone + ']!KeyPress Volume ' + volume + '\r'

		elif action == "turnonvolume":
			attr=result["volume"]
			cmd='SET C[' + str(c) + '].Z[' + zone + '].' + action + '="' + attr + '"\r'

		elif action == "bass":
			attr=result["bass"]
			cmd='SET C[' + str(c) + '].Z[' + zone + '].' + action + '="' + attr + '"\r'

		elif action == "balance":
			attr=result["balance"]
			cmd='SET C[' + str(c) + '].Z[' + zone + '].' + action + '="' + attr + '"\r'

		elif action == "treble":
			attr=result["treble"]
			cmd='SET C[' + str(c) + '].Z[' + zone + '].' + action + '="' + attr + '"\r'

		else:
			return 401
	
		sendCommand(cmd)
		return 200

	except Exception as err:
		debugFunction(0, "EXCEPTION - checkCommand: " + str(err))
		if err.errno == errno.EPIPE:
			return errno.EPIPE
		else:
			return 401

def prepareResponse(request):

	debugFunction(1, "prepareResponse: request=" + request)

	response=""

	if request == 'zoneconfig':
		response += json.dumps(ZoneConfig)

	elif str(request) == 'sourceconfig':
		response += json.dumps(SourceConfig)

	elif request == 'channels':
		response += json.dumps(Channels)

	elif request == 'defaultchannels':
		response += json.dumps(DefChannel)

	elif re.search(r'status.*', request, 0):
		response += \
			'{ "StartDate": ' + json.dumps(startdate.strftime("%d.%m.%Y %H:%M:%S")) + \
			', "LastReconnect": ' + json.dumps(lastconnect.strftime("%d.%m.%Y %H:%M:%S")) + \
			', "ConnectErrorDate": ' + json.dumps(ConnectErrorDate.strftime("%d.%m.%Y %H:%M:%S")) + \
			', "DeviceVersion": ' + json.dumps(DeviceVersion) + \
			', "DeviceStatus": ' + json.dumps(DeviceStatus) + \
			', "ZoneCount": ' + json.dumps(ZoneCount) + \
			', "ControllerType": ' + json.dumps(ControllerType) + \
			', "CountSource": ' + json.dumps(SourceCount) + \
			', "ConvertErrorStr": ' + json.dumps(ConvertErrorStr) + \
			', "ConvertErrorHex": ' + json.dumps(ConvertErrorHex) + \
			', "ConvertErrorDate": ' + json.dumps(ConvertErrorDate.strftime("%d.%m.%Y %H:%M:%S")) + \
			', "MaxDiffDate": ' + json.dumps(MaxTimeReadDiffDate.strftime("%d.%m.%Y %H:%M:%S")) + \
			', "TimebetweenRead": ' + json.dumps(str(TimebetweenRead)) + \
			', "MaxDiffTimebetweenRead": ' + json.dumps(str(MaxTimeReadDiff)) + \
			', "LastRead": ' + json.dumps(LastRead) + \
			', "LastReadDateTime": ' + json.dumps(LastReadDateTime.strftime("%d.%m.%Y %H:%M:%S")) + \
			'}'
	else:
		response += \
			'{ "ZoneConfig": ' + json.dumps(ZoneConfig) + \
			', "SourceConfig": ' + json.dumps(SourceConfig) + \
			', "Channels": ' + json.dumps(Channels) + \
			', "DefaultChannel": ' + json.dumps(DefChannel) + \
			', "StartDate": ' + json.dumps(startdate.strftime("%d.%m.%Y %H:%M:%S")) + \
			', "LastReconnect": ' + json.dumps(lastconnect.strftime("%d.%m.%Y %H:%M:%S")) + \
			', "DeviceVersion": ' + json.dumps(DeviceVersion) + \
			', "DeviceStatus": ' + json.dumps(DeviceStatus) + \
			', "CountSource": ' + json.dumps(SourceCount) + \
			'}'

	debugFunction(1, "prepareResponse: response=" + response)

	return response

def mqtt_on_connect(client, userdata, flags, rc):
	debugFunction(1, "Connected with result code "+str(rc))

	client.subscribe([(mqttTopic + MQTT_TOPIC_GET, 2),(mqttTopic + MQTT_TOPIC_SET, 2), (mqttTopic + MQTT_TOPIC_CMD, 2)])

def mqtt_on_message(client, userdata, msg):
	global debugLevel, debugHex
	try:
		payload = msg.payload.decode().strip('\n').lower()
		debugFunction(2, "mqtt_on_message: topic = " + msg.topic + " payload: " + payload)

		if msg.topic == mqttTopic + MQTT_TOPIC_GET:

			response=prepareResponse(payload)
			send2Network("mqtt:" + mqttTopic + MQTT_TOPIC_DATA, response, 1)

		elif msg.topic == mqttTopic + MQTT_TOPIC_CMD:
			rc=checkCommand(payload);

			send2Network("mqtt:" + mqttTopic + MQTT_TOPIC_ACK, \
				"Ok" if rc == 200 else str(rc) + ' - Cmd: ' + payload, 2)

		elif msg.topic == mqttTopic + MQTT_TOPIC_SET:

			result=dict(re.findall('(\w+)=([\w.+-]+)&?', payload)) # e.g debugLevel=1&debugTarget=2
			debugFunction(2, "mqtt_on_message: " + json.dumps(result))

			try:
				rc=int(result["debuglevel"])
				if rc >= 0 and rc < 4:
					debugFunction(0, "mqtt_on_message:  set debugLevel to " + str(rc))
					debugLevel=rc
			except:
				pass

			try:
				rc=int(result["debughex"])
				if rc >= 0 and rc < 2:
					debugHex=rc
					debugFunction(0, "mqtt_on_message:  set debugHex to " + str(rc))
			except:
				pass

	except Exception as e:
		debugFunction(0, "mqtt_on_message: "+ str(e))

def MQTTService(mqttHost, mqttPort, mqttTopic, mqttUser, mqttPass):
	global mqtt_client
	
	debugFunction (0, 'Connect MQTT to ' + mqttHost + ' on port ' + str(mqttPort) + ', SSL is ' + str(usemqttssl) + \
		', with Topic ' + mqttTopic)
	try:
		mqtt_client = mqtt.Client()
		if usemqttssl:
			mqtt_client.tls_set(mqttcertificatefile, tls_version=ssl.PROTOCOL_TLSv1_2)
			mqtt_client.tls_insecure_set(True)
			
		if mqttUser:
			mqtt_client.username_pw_set(mqttUser, mqttPass)

		mqtt_client.connect(mqttHost, mqttPort)

		mqtt_client.on_connect = mqtt_on_connect
		mqtt_client.on_message = mqtt_on_message

		mqtt_client.loop_forever()

	except Exception as e:
		debugFunction(0, "MQTT Service Initiation: "+ str(e))

def WebService(usessl, wport):
	
	client_connection=None

	while True:

		if not client_connection:
			HOST = ''
			listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
			listen_socket.bind((HOST, wport))
			listen_socket.listen(1)

			if usessl:
				context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
				context.load_cert_chain(certfile=certificatefile)  
				context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1  # optional
				context.set_ciphers('EECDH+AESGCM:EDH+AESGCM:AES256+EECDH:AES256+EDH')

			debugFunction (0, 'Serving HTTP on port ' + str(wport) + ', SSL is ' + str(usessl))

		conn, client_address = listen_socket.accept()
		if usessl:
			try:
				client_connection = context.wrap_socket(conn, server_side=True)
			except Exception as e:
				conn.close()
				client_connection=None
				debugFunction(0, "SSL-Error: "+ str(e))

		else:
			client_connection=conn
		
		try:
			
			request = client_connection.recv(1024).decode('utf-8', 'ignore')
			now = datetime.datetime.now()
			
			debugFunction(1, request)
			if re.search(r'^GET /(.*) HTTP', request, 0):  
				res=re.split(r'^GET /(.*) HTTP', request, 0)
				result=res[1].lower()
				
				debugFunction(1, "Result: " + result)

				http_response = "HTTP/1.1 200 OK\nCache-Control: no-cache\nAccess-Control-Allow-Origin: *\nContent-Type: application/json\n\n"

				if re.search(r'^cmd\?(.*)', result, 0): #GET /cmd?zone=1&source=1?status=1
					res=re.split(r'^cmd\?(.*)', result, 0); 
					rc=checkCommand(res[1])
					http_response = 'HTTP/1.1 ' + str(rc) + ' OK\nAccess-Control-Allow-Origin: *\n\n<html></html>'

					if rc==errno.EPIPE:
						raise Exception("CheckCommand:Broken Pipe")
				else:
					http_response += prepareResponse(result)

			client_connection.sendall(http_response.encode())
			client_connection.close()
			client_connection=None

				
		except Exception as e:
			debugFunction(0, "Error: "+ str(e))
			client_connection=None

		
def main(argv):
	global host, wport, port, SSLPort, usessl, useWeb, useMQTT, debugTarget, debugLevel, macAddr, \
		mqttTopic, mqttHost, mqttPort, mqttUser, mqttPass, usemqttssl, mqttcertificatefile, \
		remoteTargets, controllers, Channels, DefChannel, ignoresources, ignorezones, certificatefile
	
	config = configparser.ConfigParser()
	config.optionxform = str
	config.read([os.path.dirname(os.path.realpath(__file__)) + '/riod.ini', '/etc/riod.ini', '/usr/local/etc/riod.ini'])

	try:
		remoteTargets=dict(config.items('RemoteTargets'))
		debugFunction(2, "remoteTargets: " + json.dumps(remoteTargets))
	except:
		remoteTargets=[]

	try:
		Channels=dict(config.items('Channels'))
	except:
		Channels=[]
		
	try:
		DefChannel = config.get("FavouriteChannels","Fav1")
	except:
		DefChannel = ""
			
	try:
		ignoresources=config.get("Common","IgnoreSources").split(',')
		ignoresources = list(map(int, ignoresources))
	except:
		ignoresources=[]
	debugFunction(2, "IgnoreSources: " + json.dumps(ignoresources))

	
	try:
		ignorezones=config.get("Common","IgnoreZones").split(',')
		ignorezones=list(map(int, ignorezones))
	except:
		ignorezones=[]
	debugFunction(2, "IgnoreZones: " + json.dumps(ignorezones))

	try:
		macAddr = config.get("Common","MAC")
	except:
		maxAddr=None
	
	try:
		useWeb=int(config.get("Webserver","EnableWeb"))
	except:
		useWeb=1

	try:
		usessl=int(config.get("Webserver","EnableSSL"))
		if usessl == 1:
			certificatefile=config.get("Webserver","Certificate")
			debugFunction(0, "Certificate file is missing in ini - fallback to http")
			SSLPort=int(config.get("Webserver","SSLPort"))		
			debugFunction(0, "SSL port missing in ini - fallback to http")
	except:
		usesll=0

	try:
		useMQTT=int(config.get("MQTT","EnableMQTT"))

		if useMQTT:
			mqttHost=config.get("MQTT","Host")
			try:
				mqttPort=int(config.get("MQTT","Port"))
			except:
				mqttPort=1883
			mqttTopic=config.get("MQTT","Topic")
			
			try:
				mqttUser=config.get("MQTT","username")
				mqttPass=config.get("MQTT","password")
			except:
				mqttUser=False
				mqttPass=False
		
			try:
				usemqttssl=int(config.get("MQTT","EnableMQTTSSL"))
				if usemqttssl == 1:
					mqttcertificatefile=config.get("MQTT","Certificate")
					debugFunction(0, "MQTT Certificate file is missing in ini")
			except:
				usemqttssl=0
		
	except:
		useMQTT=0


	controllers=config.get("Common","Controllers").split(',')	
	host=config.get("Common","Russound")
	port=int(config.get("Common","Port"))
	wport=int(config.get("Webserver","Port"))
	
	parser = optparse.OptionParser()
	parser.add_option('-d', '--debug',
		dest="debugLevel",
		default=0,
		action="store",
		type="int",
	)
	parser.add_option('-t', '--target',
		dest="debugTarget",
		default=0,
		action="store",
		type="int",
	)
	parser.add_option('-r', '--russound',
		dest="russound",
		action="store",
		type="string",
	)
	parser.add_option('-w', '--wport',
		dest="wport",
		action="store",
		type="int",
	)
	parser.add_option('--sslport',
		dest="sslport",
		action="store",
		type="int",
	)
	parser.add_option('-p', '--port',
		dest="port",
		action="store",
		type="int",
	)
	parser.add_option('-s', '--usessl',
		dest="usessl",
		action="store",
		type="int",
	)
	parser.add_option('-m', '--mac',
		dest="mac",
		action="store",
		type="string",
	)

	options, remainder = parser.parse_args()
	
	if options.russound is not None:
		host=options.russound
	if options.wport is not None:
		wport=options.wport
	if options.mac is not None:
		macAddr=options.mac
	if options.port is not None:
		port=options.port
	if options.sslport is not None:
		SSLPort=options.sslport
	if options.usessl is not None:
		usessl=options.usessl

	if controllers is None:
		controllers=["1"]
		
	if host is None:
		print('Russound address not given')
		sys.exit(2)
		
	if port is None:
		port=9621
		
	if wport is None:
		print('Webserver Port not given')
		sys.exit(2)

	debugLevel=options.debugLevel
	debugTarget=options.debugTarget

	debugFunction(1, "Russound address: " + host + ", Port: " + str(port))
	debugFunction(1, "Webserver Port: " + str(wport))
	debugFunction(1, "SSL: " + str(usessl))
	debugFunction(1, "Webserver: " + str(useWeb))
	debugFunction(1, "MQTT: " + str(useMQTT))

	if useMQTT == 1:
		debugFunction(1, "MQTT Host: " + mqttHost)
		debugFunction(1, "MQTT Port: " + str(mqttPort))
		debugFunction(1, "MQTT Topic: " + mqttTopic)
		debugFunction(1, "MQTT User: " + mqttUser)
		debugFunction(1, "MQTT Pass: " + mqttPass)

	if usessl:
		debugFunction(1, "SSL Webserver Port: " + str(SSLPort))
		debugFunction(1, "Certificate: " + certificatefile)

	debugFunction(1, "Controller : " + json.dumps(controllers))

	debugFunction(1, "IgnoreZone : " + json.dumps(ignorezones))
	debugFunction(1, "IgnoreSource : " + json.dumps(ignoresources))
	debugFunction(1, "remote Target : " + json.dumps(remoteTargets))

	
if __name__ == "__main__":
	main(sys.argv[1:])

t1 = threading.Thread(target=watchRussound, args=(host, port, remoteTargets))
t2 = threading.Thread(target=WebService, args=(0, wport))

startdate=datetime.datetime.now()
	
t1.daemon = True
t1.start()

if useWeb:
	debugFunction(1, "Starting Web-Service...")

	t2.daemon = True
	t2.start()

if useMQTT == 1:
	debugFunction(1, "Starting MQTT-Service...")

	t3 = threading.Thread(target=MQTTService, args=(mqttHost, mqttPort, mqttTopic, mqttUser, mqttPass))
	t3.start()


if usessl == 1:
	debugFunction(1, "Starting SSL-Service...")

	t4 = threading.Thread(target=WebService, args=(1, SSLPort))
	t4.start()	


t1.join()


