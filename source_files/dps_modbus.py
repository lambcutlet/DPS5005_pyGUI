import minimalmodbus
import time
import csv
try:
	import ConfigParser
except ImportError:
	import configparser as ConfigParser

''' 
import the system limit thresholds from the *.ini file.
having a separate file allows simple modification for other versions of DPS supplies.
these limits prevent the program from issuing silly values.
'''
class Import_limits:
	def __init__(self, filename):
		Config = ConfigParser.ConfigParser()
		Config.read(filename)
		b = Config.options('SectionOne')		# safety limits
		for x in range(len(b)):
			c = b[x]
			exec("self.%s = %s" % (c, Config.get('SectionOne', c)))	
		
		b = Config.options('SectionTwo')		# decimal places
		for x in range(len(b)):
			c = b[x]
			exec("self.%s = %s" % (c, Config.get('SectionTwo', c)))		

'''
# original inspiration for this came from here:
# DPS3005 MODBUS Example By Luke (www.ls-homeprojects.co.uk) 
#
# Requires minimalmodbus library from: https://github.com/pyhys/minimalmodbus
'''		
class Serial_modbus:
	def __init__(self, port1, addr, baud_rate, byte_size ):
		self.instrument = minimalmodbus.Instrument(port1, addr) # port name, slave address (in decimal)
		#self.instrument.serial.port          # this is the serial port name
		self.instrument.serial.baudrate = baud_rate   # Baud rate 9600 as listed in doc
		self.instrument.serial.bytesize = byte_size
		self.instrument.serial.timeout = 0.5     # This had to be increased from the default setting else it did not work !
		self.instrument.mode = minimalmodbus.MODE_RTU  #RTU mode

	def read(self, reg_addr, decimal_places):
		return self.instrument.read_register(reg_addr, decimal_places)
		
	def read_block(self, reg_addr, size_of_block):
		return self.instrument.read_registers(reg_addr, size_of_block)
			
	def write(self, reg_addr, value, decimal_places):
		self.instrument.write_register(reg_addr, value, decimal_places) # register, value, No_of_decimal_places
	
	def write_block(self, reg_addr, value):
		self.instrument.write_registers(reg_addr, value)
				
class Dps5005:
#--- new ---
	def __init__(self, ser, limits):
		self.serial_data = ser
		self.limits = limits
		
	def voltage_set(self, RWaction='r', value=0.0):	# R/W
		return self.function(0x00, self.limits.decimals_vset, RWaction, value, self.limits.voltage_set_max, self.limits.voltage_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value 

	def current_set(self, RWaction='r', value=0.0):	# R/W
		return self.function(0x01, self.limits.decimals_iset, RWaction, value, self.limits.current_set_max, self.limits.current_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value 

	def voltage(self):	# R
		return self.function(0x02, self.limits.decimals_v) 

	def current(self):	# R
		return self.function(0x03, self.limits.decimals_i)

	def power(self):	# R
		return self.function(0x04, self.limits.decimals_power)

	def voltage_in(self):	# R
		return self.function(0x05, self.limits.decimals_vin)

	def lock(self, RWaction='r', value=0):	# R/W
		return self.function(0x06, 0, RWaction, value, self.limits.lock_set_max, self.limits.lock_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value

	def protect(self):	# R
		return self.function(0x07, 0)

	def cv_cc(self):	# R
		return self.function(0x08, 0)

	def onoff(self, RWaction='r', value=0):	# R/W
		return self.function(0x09, 0, RWaction, value, self.limits.onoff_set_max, self.limits.onoff_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value
		
	def b_led(self, RWaction='r', value=0):	# R/W
		return self.function(0x0A, 0, RWaction, value, self.limits.b_led_set_max, self.limits.b_led_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value

	def model(self):	# R
		return self.function(0x0B, 0)

	def version(self):	# R
		return self.function(0x0C, self.limits.decimals_version)

	def extract_m(self, RWaction='r', value=0.0):	# R/W
		return self.function(0x23, 0, RWaction, value, self.limits.extract_m_set_max, self.limits.extract_m_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value
				
#---		
		
	def voltage_set2(self, RWaction='r', value=0.0):	# R/W
		return self.function(0x50, self.limits.decimals_vset, RWaction, value, self.limits.voltage_set2_max, self.limits.voltage_set2_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value
			
	def current_set2(self, RWaction='r', value=0.0):	# R/W
		return self.function(0x51, self.limits.decimals_iset, RWaction, value, self.limits.current_set2_max, self.limits.current_set2_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value

	def s_ovp(self, RWaction='r', value=0):	# R/W
		return self.function(0x52, self.limits.decimals_ovp, RWaction, value, self.limits.s_ovp_set_max, self.limits.s_ovp_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value
		
	def s_ocp(self, RWaction='r', value=0):	# R/W
		return self.function(0x53, self.limits.decimals_ocp, RWaction, value, self.limits.s_ocp_set_max, self.limits.s_ocp_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value

	def s_opp(self, RWaction='r', value=0):	# R/W
		return self.function(0x54, self.limits.decimals_opp, RWaction, value, self.limits.s_opp_set_max, self.limits.s_opp_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value

	def b_led2(self, RWaction='r', value=0):	# R/W
		return self.function(0x55, 0, RWaction, value, self.limits.b_led2_set_max, self.limits.b_led2_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value

	def m_pre(self, RWaction='r', value=0):	# R/W
		return self.function(0x56, 0, RWaction, value, self.limits.m_pre_set_max, self.limits.m_pre_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value
	
	def s_ini(self, RWaction='r', value=0):	# R/W
		return self.function(0x57, 0, RWaction, value, self.limits.s_ini_set_max, self.limits.s_ini_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value

	def read_all(self, RWaction='r', value=0.0):	# Read data as a block, much faster than individual reads
		data = self.functions(0x00, 16, RWaction, value) # reg_addr, number of bytes, RWaction, value
		#--- adjust values to floating points
		data[0] = data[0] / float(10**self.limits.decimals_vset)	#100.0	# voltage_set
		data[1] = data[1] / float(10**self.limits.decimals_iset)	#1000.0	# current_set
		data[2] = data[2] / float(10**self.limits.decimals_v)	#100.0	# voltage
		data[3] = data[3] / float(10**self.limits.decimals_i)	#1000.0	# current
		data[4] = data[4] / float(10**self.limits.decimals_power)	#100.0	# power
		data[5] = data[5] / float(10**self.limits.decimals_vin)	#100.0	# voltage_in
		data[12] = data[12] / float(10**self.limits.decimals_version)	#10.0	# version
		return data
	
	def write_voltage_current(self, RWaction='r', value=0):	# write voltage & current as a block
		reg_addr = 0x00 
		# added safety limits - any excursion results in zero
		if value[0] > self.limits.voltage_set_max or value[0] < self.limits.voltage_set_min: 
			value[0] = 0
		value[0] = int(value[0] * float(10**self.limits.decimals_v))	#100.0	# voltage
		if value[1] > self.limits.current_set_max or value[1] < self.limits.current_set_min: 
			value[1] = 0
		value[1] = int(value[1] * float(10**self.limits.decimals_i))	#1000.0	# current
		
		self.functions(reg_addr, 0, 'w', value)
		
	def write_all(self, reg_addr=0, value=0):	# write block
		self.functions(reg_addr, 0, 'w', value)
		
#---
	def function(self, reg_addr=0, decimal_places=0, RWaction='r', value=0.0, max_value=0, min_value=0):
		a = False
		if value > max_value or value < min_value: 
			value = 0.0
		if RWaction != 'w':
			try:
				a = self.serial_data.read(reg_addr, decimal_places)
			except IOError:
				print("Failed to read from instrument")
		else:
			try:
				self.serial_data.write(reg_addr, value, decimal_places) # register, value, No_of_decimal_places
			except IOError:
				print("Failed to write to instrument")
		return(a)
	
	def functions(self, reg_addr=0, num_of_addr=0, RWaction='r', value=0):
		a = False
		if RWaction != 'w':
			try:
				a = self.serial_data.read_block(reg_addr, num_of_addr)
			except IOError:
				print("Failed to read block from instrument")
		else:
			try:
				self.serial_data.write_block(reg_addr, value)
			except IOError:
				print("Failed to write block to instrument")
		return(a)
	
	def delay(self, value):
		global time_old
		value = float(value)
		if value == 0.0:
			time_old = time.time()

		while True:
			time_interval = time.time() - time_old
			if time_interval >= value:
				time_old = time.time()
				break
			time.sleep(0.01)
			
	def action_csv_file(self, filename='sample.csv', value=0):
		try:
			with open(filename, 'r') as f:
				csvReader = csv.reader(f)#, delimiter=',')	# reads file
				next(csvReader, None)						# skips header
				data_list = list(csvReader)
				print(data_list)
			# initialise dps state
				self.voltage_set('w', float(0.0))			# set voltage to zero
				self.current_set('w', float(0.0))			# set current to zero
				self.onoff('w', 1)							# enable output
				total_time = 0
			# calculate test time
				for row in data_list:
					total_time += float(row[0])
				print("Test Time: %5.1fseconds" % (total_time))
			# perform test
				for row in data_list:
					value0 = float(row[0])
					value1 = float(row[1])
					value2 = float(row[2])
					print(" Step_time: %5.1fs, Voltage: %5.2fV, Current: %5.3fA" % (value0, value1, value2))
					self.voltage_set('w', value1)
					self.current_set('w', value2)
					self.delay(value0)
			self.onoff('w', 0)							# disable output
			print("Complete!")
			return
		except:
			print("Failed to load file.")
'''
This file can operate independently controlling the DPS via the commandline however the GUI is much simpler.
'''
if __name__ == '__main__':
	ser = Serial_modbus('/dev/ttyUSB1', 1, 9600, 8)
	limits = Import_limits("dps5005_limits.ini")
	dps = Dps5005(ser, limits)
	try:
		while True:
			route = raw_input("Enter command: ")
			if route == "q":
				quit()
			elif route == "read":
				start = time.time()
				print(dps.read_all())
				print(time.time() - start)	
			elif route == "write":
				value = [23.47, 1.234]
				dps.write_voltage_current('w', value)
			elif route == "r":
				start = time.time()
				print("voltage_set :  %6.2f" % dps.voltage_set())
				print(time.time() - start)
				print("current_set :  %6.3f" % dps.current_set())	
				print("voltage     :  %6.2f" % dps.voltage())
				print("current     :  %6.2f" % dps.current())
				print("power       :  %6.2f" % dps.power())
				print("voltage_in  :  %6.2f" % dps.voltage_in())
		
				print("lock        :  %6s" % dps.lock())
				print("protection  :  %6s" % dps.protect())	
				print("cv_cc       :  %6s" % dps.cv_cc())
				print("onoff       :  %6s" % dps.onoff())
				print("b_led       :  %6s" % dps.b_led())
				print("model       :  %6s" % dps.model())
				print("version     :  %6s" % dps.version())
				print("extract_m   :  %6s" % dps.extract_m())
				
				print("voltage_set2:  %6s" % dps.voltage_set2())	
				print("current_set2:  %6s" % dps.current_set2())
				print("s_ovp       :  %6s" % dps.s_ovp())
				print("s_ocp       :  %6s" % dps.s_ocp())
				print("s_opp       :  %6s" % dps.s_opp())
				print("b_led2      :  %6s" % dps.b_led2())
				print("m_pre       :  %6s" % dps.m_pre())
				print("s_ini       :  %6s" % dps.s_ini())
				
			elif route == "vset":
				value = raw_input("Enter value: ")
				dps.voltage_set('w', float(value))
			elif route == "iset":
				value = raw_input("Enter value: ")
				dps.current_set('w', float(value))
			elif route == "lock":
				value = raw_input("Enter value: ")
				dps.lock('w', float(value))
			elif route == "on":
				dps.onoff('w', 1)
			elif route == "off":
				dps.onoff('w', 0)		
			elif route == "bled":
				value = raw_input("Enter value: ")
				dps.b_led('w', float(value))		
			elif route == "sovp":
				value = raw_input("Enter value: ")
				dps.s_ovp('w', float(value))
			elif route == "socp":
				value = raw_input("Enter value: ")
				dps.s_ocp('w', float(value))
			elif route == "sopp":
				value = raw_input("Enter value: ")
				dps.s_opp('w', float(value))	
			elif route == "sini":
				value = raw_input("Enter value: ")
				dps.s_ini('w', float(value))
			elif route == "m":	
				for i in dir(dps):
					print(i)
			elif route == "a":	
				dps.action_csv_file('dps-control-Book1.csv')
			else:
				pass

	except KeyboardInterrupt:  	# Ctrl+C pressed, so...
		print("close")
	finally:
		dps.onoff('w', 0)
		quit()
