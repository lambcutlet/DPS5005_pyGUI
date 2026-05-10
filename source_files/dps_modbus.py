import minimalmodbus
import time
import csv
import configparser
import logging

# Setup logging instead of just printing
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Import_limits:
	def __init__(self, filename):
		config = configparser.ConfigParser()
		config.read(filename)
		
		# Use setattr instead of exec() for safety
		for section in ['SectionOne', 'SectionTwo', 'SectionThree']:
			if config.has_section(section):
				for key in config.options(section):
					val = config.get(section, key)
					# Attempt to convert to float/int if possible
					try:
						val = int(val)
					except ValueError:
						try:
							val = float(val)
						except ValueError:
							if key == 'port_set':
								val = val.split('#')[0]
								val = val.strip().strip("'\"")
							else:
								val = val[0:3]
								val = val.strip("'")
					message = ("self.%s = %s" % (key, val))
					try:
						setattr(self, key, val)
					except:
						pass
		return
		
class Serial_modbus:
	def __init__(self, port, addr, baud_rate=9600, byte_size=8, timeout=0.5):
		self.instrument = minimalmodbus.Instrument(port, addr)
		self.instrument.serial.baudrate = baud_rate
		self.instrument.serial.bytesize = byte_size
		self.instrument.serial.timeout = timeout
		self.instrument.mode = minimalmodbus.MODE_RTU
		self.max_retries = 3

	def _execute(self, func, action_name, reg_addr, *args, **kwargs):
		"""Helper to handle retries and logging for all modbus operations."""
		for attempt in range(1, self.max_retries + 1):
			try:
				result = func(reg_addr, *args, **kwargs)
				logger.info(f"{action_name} success on attempt {attempt} at {reg_addr}")
				return result
			except Exception as e:
				logger.warning(f"{action_name} attempt {attempt} failed at {reg_addr}: {e}")
				if attempt < self.max_retries:
					time.sleep(0.1)  # Brief pause often helps serial stability
		
		logger.error(f"All {self.max_retries} attempts failed for {action_name} at {reg_addr}")
		return None

	def read(self, reg_addr, decimal_places=0): return self._execute(self.instrument.read_register, 'read', reg_addr, decimal_places)
	def read_block(self, reg_addr, size): return self._execute(self.instrument.read_registers, 'read_block', reg_addr, size)
	def write(self, reg_addr, value, decimal_places=0): return self._execute(self.instrument.write_register, 'write', reg_addr, value, decimal_places)
	def write_block(self, reg_addr, values): return self._execute(self.instrument.write_registers, 'write_block', reg_addr, values)

class Dps5005:
	def __init__(self, ser, limits):
		self.serial_data = ser
		self.limits = limits

	def _execute_rw(self, reg, decimals, action, value, v_max=None, v_min=None):
		"""Internal helper to handle bounds checking and R/W logic."""
		if action == 'w':
			# Safety: Clip value to limits instead of resetting to 0
			if v_max is not None:
				value = max(v_min, min(value, v_max))
			return self.serial_data.write(reg, value, decimals)
		return self.serial_data.read(reg, decimals)
	
	def _execute_rw_block(self, reg, size_or_values, action, values=None):
		"""
		Fixed to distinguish between reading (size) and writing (list of values).
		"""
		if action == 'w':
			# Safety: The calling function should handle scaling/clipping
			return self.serial_data.write_block(reg, values)
		# In 'read' mode, size_or_values is the number of registers to read
		return self.serial_data.read_block(reg, size_or_values)

	# --- Simplified Property-like Methods ---
	def voltage_set(self, action='r', val=0.0): return self._execute_rw(0x00, self.limits.decimals_vset, action, val, self.limits.voltage_set_max, self.limits.voltage_set_min)
	def current_set(self, action='r', val=0.0): return self._execute_rw(0x01, self.limits.decimals_iset, action, val, self.limits.current_set_max, self.limits.current_set_min)
	def voltage(self): return self.serial_data.read(0x02, self.limits.decimals_v)
	def current(self): return self.serial_data.read(0x03, self.limits.decimals_i)
	def power(self): return self.serial_data.read(0x04, self.limits.decimals_power)
	def voltage_in(self): return self.serial_data.read(0x05, self.limits.decimals_vin)
	def lock(self, action='r', val=0): return self._execute_rw(0x06, 0, action, val, self.limits.lock_set_max, self.limits.lock_set_min)
	def protect(self): return self.serial_data.read(0x07, 0)
	def cv_cc(self): return self.serial_data.read(0x08, 0)
	def onoff(self, action='r', val=0): return self._execute_rw(0x09, 0, action, val, self.limits.onoff_set_max, 0)
	def b_led(self, action='r', val=0): return self._execute_rw(0x0A, 0, action, val, self.limits.b_led_set_max, self.limits.b_led_set_min)
	def model(self): return self.serial_data.read(0x0B, 0)
	def version(self): return self.serial_data.read(0x0C, 0)
	def extract_m(self, action='r', val=0.0): return self._execute_rw(0x23, 0, action, val, self.limits.extract_m_set_max, self.limits.extract_m_set_min)  
	def voltage_set2(self, action='r', val=0.0): return self._execute_rw(0x50, self.limits.decimals_vset, action, val, self.limits.voltage_set2_max, self.limits.voltage_set2_min)  
	def current_set2(self, action='r', val=0.0): return self._execute_rw(0x51, self.limits.decimals_iset, action, val, self.limits.current_set2_max, self.limits.current_set2_min)  
	def s_ovp(self, action='r', val=0): return self._execute_rw(0x52, self.limits.decimals_ovp, action, val, self.limits.s_ovp_set_max, self.limits.s_ovp_set_min)  
	def s_ocp(self, action='r', val=0): return self._execute_rw(0x53, self.limits.decimals_ocp, action, val, self.limits.s_ocp_set_max, self.limits.s_ocp_set_min)  
	def s_opp(self, action='r', val=0): return self._execute_rw(0x54, self.limits.decimals_opp, action, val, self.limits.s_opp_set_max, self.limits.s_opp_set_min)  
	def b_led2(self, action='r', val=0): return self._execute_rw(0x55, 0, action, val, self.limits.b_led2_set_max, self.limits.b_led2_set_min)  
	def m_pre(self, action='r', val=0): return self._execute_rw(0x56, 0, action, val, self.limits.m_pre_set_max, self.limits.m_pre_set_min)  
	def s_ini(self, action='r', val=0): return self._execute_rw(0x57, 0, action, val, self.limits.s_ini_set_max, self.limits.s_ini_set_min)

	def write_voltage_current(self, action, val):
		"""Writes voltage and current simultaneously as a block."""
		# 1. Clip values to safety limits
		v_clipped = max(self.limits.voltage_set_min, min(val[0], self.limits.voltage_set_max))
		i_clipped = max(self.limits.current_set_min, min(val[1], self.limits.current_set_max))
		# 2. Scale to integers based on decimal settings (e.g., 5.00 -> 500)
		v_raw = int(v_clipped * (10**self.limits.decimals_vset))
		i_raw = int(i_clipped * (10**self.limits.decimals_iset))
		logger.info(f"Block Write: {v_clipped}V, {i_clipped}A (Raw: {v_raw}, {i_raw})")
		# 3. Execute write (0x00 is start addr for V, then I follows at 0x01)
		return self._execute_rw_block(0x00, 2, action, [v_raw, i_raw])

	def read_all(self, action='r', val=0):
		"""Reads block and scales values dynamically."""
		raw_data = self.serial_data.read_block(0x00, 16)
		if not raw_data:
			return None
			
		# Map indices to their respective decimal dividers
		scaling = {
			0: self.limits.decimals_vset, 1: self.limits.decimals_iset,
			2: self.limits.decimals_v,    3: self.limits.decimals_i,
			4: self.limits.decimals_power, 5: self.limits.decimals_vin,
			12: self.limits.decimals_version
		}
		return [val / (10**scaling.get(i, 0)) for i, val in enumerate(raw_data)]

	def action_csv_file(self, filename):
		"""Executes CSV profile using the interval between timestamps for timing."""
		try:
			with open(filename, 'r') as f:
				reader = list(csv.reader(f))
				header, data = reader[0], reader[1:]
			self.onoff('w', 1)
			previous_time = None
			for row in data:
				# Ensure row has enough data to unpack
				if not row or len(row) < 3:
					continue
				current_timestamp, v, i = map(float, row)
				# Calculate sleep duration based on the interval from the last row
				if previous_time is not None:
					interval = current_timestamp - previous_time
					if interval > 0:
						time.sleep(interval)
				logger.info(f"Setting: {v}V, {i}A (Timestamp: {current_timestamp}s)")
				# Apply settings
				self.voltage_set('w', v)
				self.current_set('w', i)
				# Update reference for next iteration
				previous_time = current_timestamp
			self.onoff('w', 0)
			logger.info("Profile Complete")
		except Exception as e:
			logger.error(f"CSV Profile Failed: {e}")

'''
This file can operate independently controlling the DPS via the commandline however the GUI is much simpler.
'''
if __name__ == '__main__':
	ser = Serial_modbus('/dev/ttyUSB0', 1, 9600, 8)
	limits = Import_limits("dps5005_limits.ini")
	dps = Dps5005(ser, limits)
	try:
		while True:
			route = input("Enter command: ")
			if route == "q":
				quit()
			elif route == "read":
				start = time.time()
				logger.info(dps.read_all())
				logger.info(time.time() - start)	
			elif route == "write":
				value = [23.47, 1.234]
				dps.write_voltage_current('w', value)
			elif route == "r":
				start = time.time()
				logger.info("voltage_set :  %6.2f" % dps.voltage_set())
				#logger.info(time.time() - start)
				logger.info("current_set :  %6.3f" % dps.current_set())	
				logger.info("voltage     :  %6.2f" % dps.voltage())
				logger.info("current     :  %6.2f" % dps.current())
				logger.info("power       :  %6.2f" % dps.power())
				logger.info("voltage_in  :  %6.2f" % dps.voltage_in())
		
				logger.info("lock        :  %6s" % dps.lock())
				logger.info("protection  :  %6s" % dps.protect())	
				logger.info("cv_cc       :  %6s" % dps.cv_cc())
				logger.info("onoff       :  %6s" % dps.onoff())
				logger.info("b_led       :  %6s" % dps.b_led())
				logger.info("model       :  %6s" % dps.model())
				logger.info("version     :  %6s" % dps.version())
				logger.info("extract_m   :  %6s" % dps.extract_m())
				
				logger.info("voltage_set2:  %6s" % dps.voltage_set2())	
				logger.info("current_set2:  %6s" % dps.current_set2())
				logger.info("s_ovp       :  %6s" % dps.s_ovp())
				logger.info("s_ocp       :  %6s" % dps.s_ocp())
				logger.info("s_opp       :  %6s" % dps.s_opp())
				logger.info("b_led2      :  %6s" % dps.b_led2())
				logger.info("m_pre       :  %6s" % dps.m_pre())
				logger.info("s_ini       :  %6s" % dps.s_ini())
				
			elif route == "ver":
				logger.info("version     :  %6s" % dps.version())
			elif route == "vset":
				value = input("Enter value: ")
				dps.voltage_set('w', float(value))
			elif route == "iset":
				value = input("Enter value: ")
				dps.current_set('w', float(value))
			elif route == "lock":
				value = input("Enter value: ")
				dps.lock('w', float(value))
			elif route == "on":
				dps.onoff('w', 1)
			elif route == "off":
				dps.onoff('w', 0)		
			elif route == "bled":
				value = input("Enter value: ")
				dps.b_led('w', float(value))		
			elif route == "sovp":
				value = input("Enter value: ")
				dps.s_ovp('w', float(value))
			elif route == "socp":
				value = input("Enter value: ")
				dps.s_ocp('w', float(value))
			elif route == "sopp":
				value = input("Enter value: ")
				dps.s_opp('w', float(value))	
			elif route == "sini":
				value = input("Enter value: ")
				dps.s_ini('w', float(value))
			elif route == "m":	
				for i in dir(dps):
					logger.info(i)
			elif route == "a":	
				dps.action_csv_file('Sample.csv')
			else:
				pass

	except KeyboardInterrupt:  	# Ctrl+C pressed, so...
		logger.error("close")
	except Exception as e:
		# 'e' captures the error details
		logger.error(f"Reason for fault: {e}")
	finally:
		logger.error("final")
		dps.onoff('w', 0)
		quit()
