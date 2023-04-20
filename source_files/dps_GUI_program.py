import traceback, sys
#import subprocess
import glob
import serial
import time
#import os
import csv
import datetime

from dps_modbus import Serial_modbus
from dps_modbus import Dps5005
from dps_modbus import Import_limits

from PyQt5.QtCore import pyqtSlot, pyqtSignal, QRunnable, QThreadPool, QTimer, QThread, QCoreApplication, QObject, QMutex, Qt
from PyQt5.QtWidgets import QApplication, QMainWindow, QSlider, QAction, QFileDialog, QGraphicsView
from PyQt5.QtGui import QIcon, QFont
from PyQt5.uic import loadUi
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)

import pyqtgraph as pg
import numpy as np

dps = 0
dps_mode = 0 # 0 PSU default, 1 nicad, 2 li-ion, 3 CSV, 


class WorkerSignals(QObject):
	finished = pyqtSignal()
	error = pyqtSignal(tuple)
	result = pyqtSignal(object)
	progress = pyqtSignal(int)

class Worker(QRunnable):
	def __init__(self, fn, *args, **kwargs):
		super(Worker, self).__init__()
		# Store constructor arguments (re-used for processing)
		self.fn = fn
		self.args = args
		self.kwargs = kwargs
		self.signals = WorkerSignals()

		# Add the callback to our kwargs
		kwargs['progress_callback'] = self.signals.progress

	@pyqtSlot()
	def run(self):
		'''
		Initialise the runner function with passed args, kwargs.
		'''
		try:
			result = self.fn(*self.args, **self.kwargs)
		except:
			traceback.print_exc()
			exctype, value = sys.exc_info()[:2]
			self.signals.error.emit((exctype, value, traceback.format_exc()))
		else:
			self.signals.result.emit(result)  # Return the result of the processing
		finally:
			self.signals.finished.emit()  # Done


class dps_GUI(QMainWindow):
	def __init__(self):
		self.limits = Import_limits("dps5005_limits.ini")
			
		pg.setConfigOption('background', self.limits.background_colour)
			
		super(dps_GUI,self).__init__()
		loadUi('dps_GUI.ui', self)
		
		self.setWindowTitle('DPS5005_pyGUI')
		
		self.mutex = QMutex()
		
	#--- fix font style & size, mainly for HighDpiScaling
		f = QFont("Liberation Sans", 10)
		self.setFont(f)
	
	#--- PlotWidget
		self.pg_plot_setup()
		
	#--- threading
		self.threadpool = QThreadPool()
	#   print("Multithreading with maximum %d threads" % self.threadpool.maxThreadCount())
		
	#--- globals
		self.serialconnected = False
		self.slider_in_use = False
		self.CSV_file = ''
		self.CSV_list = []
		self.graph_X = []
		self.graph_Y1 = []
		self.graph_Y2 = []
		self.time_old = ""
		self.capacity_time_old = ""
		self.capacity = 0.0
		
	#--- connect signals + keyboard shortcuts + status tips
		self.pushButton_save_plot.clicked.connect(self.pushButton_save_plot_clicked)
		self.pushButton_save_plot.setShortcut(Qt.CTRL | Qt.Key_S)					# 'Save Plot' - save file/plot *.csv
		self.pushButton_save_plot.setStatusTip('Save Plot - CTRL+S')
		
		self.pushButton_clear_plot.clicked.connect(self.pushButton_clear_plot_clicked)
		self.pushButton_clear_plot.setShortcut(Qt.CTRL | Qt.Key_L)					# 'Clear' - clear/new plot
		self.pushButton_clear_plot.setStatusTip('Clear Plot - CTRL+L')
		
		self.radioButton_lock.clicked.connect(self.radioButton_lock_clicked)
		self.radioButton_lock.setShortcut(Qt.CTRL | Qt.ALT | Qt.Key_L)				# 'Lock' - toggle status
		self.radioButton_lock.setStatusTip('Toggle Lock - CTRL+ALT+L')
			
		self.pushButton_onoff.clicked.connect(self.pushButton_onoff_clicked)		# On / Off
		
		self.pushButton_set.clicked.connect(self.pushButton_set_clicked)			# 'Set' - PSU
		self.pushButton_set_2.clicked.connect(self.pushButton_set_2_clicked)		# 'Set' - NiMH/NiCad
		self.pushButton_set_3.clicked.connect(self.pushButton_set_3_clicked)		# 'Set' - Li-Ion/Lipo
		
		self.pushButton_connect.clicked.connect(self.pushButton_connect_clicked)	# 'Connect'
		
		self.pushButton_CSV.clicked.connect(self.pushButton_CSV_clicked)			# 'CSV run'
		self.pushButton_CSV_clear.clicked.connect(self.pushButton_CSV_clear_clicked)# 'CSV clear'
		self.pushButton_CSV_view.clicked.connect(self.pushButton_CSV_view_clicked)	# 'CSV view'
		
		self.horizontalSlider_brightness.valueChanged.connect(self.horizontalSlider_brightness_valueChanged)
		
		self.actionOpen.triggered.connect(self.file_open)
		self.actionOpen.setShortcut(Qt.CTRL | Qt.Key_O)								# File -> Open - open file *.csv
		self.actionOpen.setStatusTip('File Open - CTRL+O')
			
		self.actionQuit.triggered.connect(self.close)
		self.actionQuit.setShortcut(Qt.CTRL | Qt.Key_Q)								# File -> Quit - quit application
		self.actionQuit.setStatusTip('Quit application - CTRL+Q')
	
	#--- do once on startup
		self.combobox_populate()

	#--- setup & run background task
		self.timer2 = QTimer()
		self.timer2.setInterval(10)
		self.timer2.timeout.connect(self.action_CSV)
		
		self.timer = QTimer()
		self.timer.setInterval(1000)
		self.timer.timeout.connect(self.loop_function)

	def closeEvent(self, event):    
		self.shutdown() # switch OFF output when application closes to prevent unmonitored charging
		
	def shutdown(self):
		if self.pushButton_onoff.isChecked() == True:   
			self.label_onoff.setText('Output      :   OFF') # off
			self.pushButton_onoff.setChecked(False)
			self.pushButton_onoff_clicked()
			print("def shutdown")
			
	def pg_plot_setup(self): # right axis not connected to automatic scaling on the left ('A' icon on bottom LHD)
		self.p1 = self.graphicsView.plotItem
		self.p1.setClipToView(True)     

	# x axis    
		self.p1.setLabel('bottom', 'Time', units='s', color=self.limits.x_colour, **{'font-size':'10pt'})
		self.p1.getAxis('bottom').setPen(pg.mkPen(color=self.limits.x_colour, width=self.limits.x_pen_weight))

	# Y1 axis   
		self.p1.setLabel('left', 'Voltage', units='V', color=self.limits.y1_colour, **{'font-size':'10pt'})
		self.pen_Y1 = pg.mkPen(color=self.limits.y1_colour, width=self.limits.y1_pen_weight)
		self.p1.getAxis('left').setPen(self.pen_Y1)
	
	# setup viewbox for right hand axis
		self.p2 = pg.ViewBox()
		self.p1.showAxis('right')
		self.p1.scene().addItem(self.p2)
		self.p1.getAxis('right').linkToView(self.p2)
		self.p2.setXLink(self.p1)

	# Y2 axis
		self.p1.setLabel('right', 'Current', units="A", color=self.limits.y2_colour, **{'font-size':'10pt'})
		self.pen_Y2 = pg.mkPen(color=self.limits.y2_colour, width=self.limits.y2_pen_weight)
		self.p1.getAxis('right').setPen(self.pen_Y2)
		
	# scales ViewBox to scene
		self.p1.vb.sigResized.connect(self.updateViews) 	
		
		
	def updateViews(self):
		self.p2.setGeometry(self.p1.vb.sceneBoundingRect())
		self.p2.linkedViewChanged(self.p1.vb, self.p2.XAxis)

#--- update graph
	def update_graph_plot(self, chart_type = 'histogram'):
		start = time.time() 
		if chart_type == 'histogram':		
			X = np.asarray(self.graph_X, dtype=np.float32)
			b = []
			for a in X:
				if len(b) == 0:
					b.append(a)
				else:
					b.append(a - 0.000001)	
					b.append(a)
			c = len(b)
			X = np.asarray(b, dtype=np.float32)
			
			Y1 = np.asarray(self.graph_Y1, dtype=np.float32)
			b = []
			for a in Y1:
				b.append(a)
				if len(b) != c:
					b.append(a)
			Y1 = np.asarray(b, dtype=np.float32)
			
			Y2 = np.asarray(self.graph_Y2, dtype=np.float32)
			b = []
			for a in Y2:
				b.append(a)
				if len(b) != c:
					b.append(a)
			Y2 = np.asarray(b, dtype=np.float32)
		else:
			X = np.asarray(self.graph_X, dtype=np.float32)
			Y1 = np.asarray(self.graph_Y1, dtype=np.float32)
			Y2 = np.asarray(self.graph_Y2, dtype=np.float32)

		self.p1.clear()
		self.p2.clear()
		
		self.p1.plot(X,Y1,pen=self.pen_Y1, name="V")
		self.p2.addItem(pg.PlotCurveItem(X,Y2,pen=self.pen_Y2, name="I"))	

		app.processEvents()
		
		a = (time.time() - start) * 1000.0
		self.label_plot_rate.setText(("Plot Rate  : %8.3fms" % (a)))
		
#--- file handling
	def file_open(self):
		filename = QFileDialog.getOpenFileName(self, "Open File", '', 'CSV(*.csv)')
		if filename[0] != '':
			self.CSV_file = filename[0]
		if self.CSV_file != '':
			self.open_CSV(self.CSV_file)    
	
	def file_save(self):
		filename, _ = QFileDialog.getSaveFileName(self, "Save File", datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")+".csv", "All Files (*);; CSV Files (*.csv)")
		if filename != '':
			rows = zip(self.graph_X, self.graph_Y1, self.graph_Y2)
			
			if sys.platform.startswith('win'):
				with open(filename, 'w', newline='') as f:					# added newline to prevent additional carriage return in windows (\r\r\n)
					writer = csv.writer(f)
					row = ['time(s)','voltage(V)','current(A)']
					writer.writerow(row)
					for row in rows:
						writer.writerow(row)
			elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
				with open(filename, 'w') as f:					# added newline to prevent additional carriage return in windows (\r\r\n)
					writer = csv.writer(f)
					row = ['time(s)','voltage(V)','current(A)']
					writer.writerow(row)
					for row in rows:
						writer.writerow(row)
			elif sys.platform.startswith('darwin'):
				with open(filename, 'w') as f:					# added newline to prevent additional carriage return in windows (\r\r\n)
					writer = csv.writer(f)
					row = ['time(s)','voltage(V)','current(A)']
					writer.writerow(row)
					for row in rows:
						writer.writerow(row)
			else:
				raise EnvironmentError('Unsupported platform')
			
			
			
		#	with open(filename, 'w', newline='') as f:					# added newline to prevent additional carriage return in windows (\r\r\n)
		#		writer = csv.writer(f)
		#		row = ['time(s)','voltage(V)','current(A)']
		#		writer.writerow(row)
		#		for row in rows:
		#			writer.writerow(row)
		
#--- thread related code
	def progress_fn(self, n):
		print("%d%% done" % n)
		
	def print_output(self, s):
		#print(s)
		pass
		
	def thread_complete(self):
		#print("THREAD COMPLETE!")
		pass
	
#--- buttons
	def pushButton_save_plot_clicked(self):
		self.file_save()

	def pushButton_clear_plot_clicked(self): 
		self.graph_X = []
		self.graph_Y1 = []
		self.graph_Y2 = []
		self.time_old = time.time()
		self.p1.clear()
		self.p2.clear()
		self.capacity_time_old = time.time()
		self.capacity = 0.0
		
	def radioButton_lock_clicked(self):
		if self.radioButton_lock.isChecked():
			self.pass_2_thread(self.lock_on_change)
		else:
			self.pass_2_thread(self.lock_off_change)
		
	# pass_2_thread - radioButton_lock_clicked
	def lock_on_change(self, progress_callback):
		self.pass_2_dps('lock', 'w', str(1))
	def lock_off_change(self, progress_callback):
		self.pass_2_dps('lock', 'w', str(0))

	def pushButton_onoff_clicked(self):
		if self.pushButton_onoff.isChecked():
			self.pushButton_on_start_time = time.time()
			self.pass_2_thread(self.on_change)
		else:
			self.pushButton_on_start_time = 0
			self.pass_2_thread(self.off_change)
		
	# pass_2_thread - pushButton_onoff_clicked
	def on_change(self, progress_callback):
		self.pass_2_dps('onoff', 'w', str(1))
	def off_change(self, progress_callback):
		self.pass_2_dps('onoff', 'w', str(0))
		
	# PSU mode - import values
	def pushButton_set_clicked(self):                   
		if self.lineEdit_vset.text() != '' or self.lineEdit_iset.text() != '':
			try:
				value1 = abs(float(self.lineEdit_vset.text()))	# added abs() to prevent applying incorrect sign
			except ValueError:
				self.lineEdit_vset.setText("Number ?")
				return
			try:
				value2 = abs(float(self.lineEdit_iset.text()))
			except ValueError:
				self.lineEdit_iset.setText("Number ?")
				return
			global dps_mode
			dps_mode = 0
			self.pass_2_dps('write_voltage_current', 'w', [value1, value2])
	
	# Nicad mode - import values
	def pushButton_set_2_clicked(self):                 
		if self.lineEdit_vset_2.text() != '' or self.lineEdit_iset_2.text() != '' or self.lineEdit_term_2.text() != '':
			try:
				value1 = abs(float(self.lineEdit_vset_2.text()))	# added abs() to prevent applying incorrect sign
			except ValueError:
				self.lineEdit_vset_2.setText("Number ?")
				return
			try:
				value2 = abs(float(self.lineEdit_iset_2.text()))
			except ValueError:
				self.lineEdit_iset_2.setText("Number ?")
				return
			try:
				value3 = abs(float(self.lineEdit_term_2.text()))
			except ValueError:
				self.lineEdit_term_2.setText("Number ?")
				return
			global dps_mode
			dps_mode = 1
			self.v_terminate = value3
			#print(self.v_terminate)
			self.v_peak = 0
			self.pass_2_dps('write_voltage_current', 'w', [value1, value2])
	
	# Li-ion mode - import values
	def pushButton_set_3_clicked(self):                 
		if self.lineEdit_vset_3.text() != '' or self.lineEdit_iset_3.text() != '' or self.lineEdit_term_3.text() != '':
			try:
				value1 = abs(float(self.lineEdit_vset_3.text()))	# added abs() to prevent applying incorrect sign
			except ValueError:
				self.lineEdit_vset_3.setText("Number ?")
				return
			try:
				value2 = abs(float(self.lineEdit_iset_3.text()))
			except ValueError:
				self.lineEdit_iset_3.setText("Number ?")
				return
			try:
				value3 = abs(float(self.lineEdit_term_3.text()))	
			except ValueError:
				self.lineEdit_term_3.setText("Number ?")
				return
			global dps_mode
			dps_mode = 2
			self.i_terminate = value3
			self.pass_2_dps('write_voltage_current', 'w', [value1, value2])		
			
	def pushButton_connect_clicked(self):
		if self.pushButton_connect.isChecked():
			self.serial_connect()
		else:
			self.serial_disconnect("Disconnected")
	
	def pushButton_CSV_clicked(self):
		if len(self.CSV_list) > 0:
			global dps_mode
			dps_mode = 3		# set to CSV mode
			self.timer2.start()	# begin 
	
	def pushButton_CSV_clear_clicked(self):
		self.stop_CSV()

	def pushButton_CSV_view_clicked(self):
		if len(self.CSV_list) > 0:
			if self.serialconnected == False:	
				self.graph_X = [row[0] for row in self.CSV_list]		# Xaxis  - time interval
				self.graph_Y1 = [row[1] for row in self.CSV_list]				# Y1axis - voltage
				self.graph_Y2 = [row[2] for row in self.CSV_list]				# Y2axis - current
				self.update_graph_plot()
			else:
				pass
		
#--- import CSV file        
	def open_CSV(self, filename):
		self.CSV_list = []
		with open(filename, 'r') as f:
			csvReader = csv.reader(f)#, delimiter=',')  # reads file
			next(csvReader, None)                       # skips header
			data_list = list(csvReader)
			for row in data_list:
				if len(row) > 2:
					self.CSV_list.append(row)
			#self.CSV_list = data_list
		self.labelCSV(len(self.CSV_list))   
				
	def labelCSV(self, value):          # display remaining steps
		self.label_CSV.setText("Steps remaining: %3d" % value)

#--- action the imported CSV using timer2       
	def action_CSV(self):
		if self.pushButton_onoff.isChecked() == True: 
			global dps_mode
			if dps_mode != 3:
				return  
			if len(self.CSV_list) > 0:
				data_list = self.CSV_list
				
				if len(self.CSV_list) > 1:			# calculate step time interval
					value0 = float(data_list[1][0]) - float(data_list[0][0])
				else:
					value0 = 0
				
				# set Voltage/Current levels
				value1 = float(data_list[0][1])
				value2 = float(data_list[0][2])
				self.pass_2_dps('write_voltage_current', 'w', [value1, value2])
				
				data_list.pop(0)
				self.timer2.stop()
				self.timer2.setInterval(int(value0)*1000)
				self.timer2.start()
				self.labelCSV(len(self.CSV_list)) 	# display No. of remaining steps
			else:
				self.stop_CSV()

	def stop_CSV(self):
		self.timer2.stop()
		self.CSV_list = []
		self.labelCSV(len(self.CSV_list)) 
		global dps_mode
		dps_mode = 0	# return to PSU mode
		
#--- slider 
	def horizontalSlider_brightness_valueChanged(self):
		self.pass_2_thread(self.slider_change)
	
	# pass_2_thread - horizontalSlider_brightness_valueChanged
	def slider_change(self, progress_callback):
		value = self.horizontalSlider_brightness.value()
		self.pass_2_dps('b_led', 'w', str(value))

#--- thread the needle  
	def pass_2_thread(self, func):
		# Pass the function to execute
		worker = Worker(func) # Any other args, kwargs are passed to the run function
		worker.signals.result.connect(self.print_output)
		worker.signals.finished.connect(self.thread_complete)
		worker.signals.progress.connect(self.progress_fn)
		self.threadpool.start(worker)

#--- loop is actioned from timer1, reading data & controlling charging  
	def loop_function(self):
		try:
			if self.serialconnected == False:
				self.serial_connect()
			self.read_all()
			self.operating_mode()
		except:
			self.serial_disconnect("Disconnected")
		
#--- operating mode 
	def operating_mode(self):
		global dps_mode
		value = dps_mode
		if value == 0:
			self.label_operating_mode.setText('PSU')
		elif value == 1:
			self.label_operating_mode.setText('NiCad')
			if float(self.vout) > float(self.v_peak):   # find peak voltage
				self.v_peak = float(self.vout)
			if self.pushButton_onoff.isChecked() and (time.time() - self.pushButton_on_start_time > 5): # adds 5sec delay, to prevent immediate switch OFF
				if float(self.vout) <= (self.v_peak - float(self.v_terminate)):     # switch off output
					self.pushButton_onoff.setChecked(False)
					self.pushButton_onoff_clicked()
		elif value == 2:
			self.label_operating_mode.setText('Li-Ion')
			if self.pushButton_onoff.isChecked() and (time.time() - self.pushButton_on_start_time > 5): # adds 5sec delay, to prevent immediate switch OFF  
				if float(self.iout) <= float(self.i_terminate):         # switch off output
					self.pushButton_onoff.setChecked(False)
					self.pushButton_onoff_clicked()
		elif value == 3:
			self.label_operating_mode.setText('CSV')
		else:
			self.label_operating_mode.setText('Invalid')

	def accrued_capacity(self, current):
		if self.capacity_time_old != '':
			self.capacity_time_current = time.time()
			self.capacity_time_interval = self.capacity_time_current - self.capacity_time_old
			self.capacity_time_old = self.capacity_time_current
			try:
				self.capacity = self.capacity + ((self.capacity_time_interval / 3600.0) * float(current))
			except ZeroDivisionError:
				self.capacity =  0.0
		#	print self.capacity
			self.label_capacity.setText("Capacity   : %8.3fAh" % self.capacity)
		else:
			self.capacity_time_old = time.time()
			
#--- read & display values from DPS 
	def read_all(self):
		data = self.pass_2_dps('read_all')
		if data != False:       
			self.vout = ("%5.2f" % data[2]) # vout
			self.iout = ("%5.3f" % data[3]) # iout
			
			self.accrued_capacity(self.iout)
			
			self.time_interval = time.time() - self.time_old			
			self.graph_X.append(self.time_interval)		# Xaxis  - time interval
			self.graph_Y1.append(self.vout)				# Y1axis - voltage
			self.graph_Y2.append(self.iout)				# Y2axis - current
			
			self.update_graph_plot()
			
			self.lcdNumber_vset.display("%5.2f" % data[0])  # vset
			self.lcdNumber_iset.display("%5.3f" % data[1])  # iset
			self.lcdNumber_vout.display(self.vout)  # vout
			self.lcdNumber_iout.display(self.iout)  # iout
			
			self.lcdNumber_pout.display("%5.2f" % data[4])  # power
			self.lcdNumber_vin.display("%5.2f" % data[5])       # vin
		# lock
			value = data[6]
			if value == 1:
				self.radioButton_lock.setChecked(True)
			else:
				self.radioButton_lock.setChecked(False)
				
		# protection
			value = data[7]
			if value == 1:
				self.label_protect.setText('Protection :   OVP')
			elif value == 2:
				self.label_protect.setText('Protection :   OCP')
			elif value == 3:
				self.label_protect.setText('Protection :   OPP')
			else:
				self.label_protect.setText('Protection :   OK')
		
		# cv/cc 
			if data[8] == 1:
				self.label_cccv.setText('Mode        :   CC')
			else:
				self.label_cccv.setText('Mode        :   CV')

		# on/off    
			value = data[9]
			if value == 1:
				self.label_onoff.setText('Output      :   ON')  # on/off
				self.pushButton_onoff.setChecked(True)
				self.pushButton_onoff.setText("ON")
			else:
				self.label_onoff.setText('Output      :   OFF') # on/off
				self.pushButton_onoff.setChecked(False)
				self.pushButton_onoff.setText("OFF")

		# slider    
			value = int(data[10])
			self.horizontalSlider_brightness.setValue(value)    # brightness
			self.label_brightness.setText('Brightness Level:   %s' % value)
			
			self.label_model.setText("Model       :   %s" % data[11])   # model
			self.label_version.setText("Version     :   %s" % data[12]) # version
	#       self.lcdNumber_iout.display(data[13])   # extract_m
	#       self.lcdNumber_iout.display(data[14])   # iout
	#       self.lcdNumber_iout.display(data[15])   # iout

#--- send commands to dps 
	def pass_2_dps(self, function, cmd = "r", value = 0):
		a = False
		if self.serialconnected != False:
			start = time.time()
			self.mutex.lock()
			a = eval("dps.%s('%s', %s)" % (function, cmd, value))
			self.mutex.unlock()
			self.label_data_rate.setText("Data Rate : %8.3fms" % ((time.time() - start) * 1000.0)) # display rate of serial comms
		return(a)
		
#--- serial selection setup       
	def combobox_datarate_read(self):
		return self.comboBox_datarate.currentText()
					
	def combobox_populate(self):        # collects info on startup		
		self.comboBox_datarate.clear()
		self.comboBox_datarate.addItems(["9600", "2400", "4800", "19200"])  # note: 2400 & 19200 doesn't seem to work

#--- serial port stuff  
	def scan_serial_ports(self):
		if sys.platform.startswith('win'):
			ports = ['COM%s' % (i + 1) for i in range(256)]
		elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
			# this excludes your current terminal "/dev/tty"
			ports = glob.glob('/dev/tty[A-Za-z]*')
		elif sys.platform.startswith('darwin'):
			ports = glob.glob('/dev/tty.*')
		else:
			raise EnvironmentError('Unsupported platform')

		result = []
		for port in ports:
			try:
				s = serial.Serial(port)
				s.flush()
				s.close()
				result.append(port)
			except (OSError, serial.SerialException):
				pass
		return result
		
	def serial_connect(self): # port autoconnects, baud rate & slave address manual inputs
		self.serialconnected = False
		try:
			global dps
			if not self.limits.port_set: 			# modified by christophjurczyk for automatic port scanning or set serial port
				# Automatic port scan
				print("Looking for ports...")
				for port in self.scan_serial_ports():
					print("Trying port: " + port)
					try:
						baudrate = abs(int(self.combobox_datarate_read()))
						slave_addr = abs(int(self.lineEdit_slave_addr.text()))
						ser = Serial_modbus(port, slave_addr, baudrate, 8)
						dps = Dps5005(ser, self.limits) #example '/dev/ttyUSB0', 1, 9600, 8)
						if dps.version() != '':
							self.serialconnected = True
							self.pushButton_connect.setText("Connected")
							self.timer.start()
							if self.time_old == "":
								self.time_old = time.time()
							print([port], baudrate, slave_addr)
							self.pushButton_CSV_view.setEnabled(False)		# disable CSV viewing capability
							self.pushButton_clear_plot_clicked()			# clear plot
							break
					except (OSError, serial.SerialException) as detail1:
						print(datetime.datetime.now().strftime("%y-%m-%d %H:%M:%S"), "Error1 - ", detail1)
						pass
			else:
				# Manual port definition in .ini file
				print("Manual port is set!")
				try:
					baudrate = abs(int(self.combobox_datarate_read()))
					slave_addr = abs(int(self.lineEdit_slave_addr.text()))
					ser = Serial_modbus(self.limits.port_set, slave_addr, baudrate, 8)
					dps = Dps5005(ser, self.limits) #example '/dev/ttyUSB0', 1, 9600, 8)
					if dps.version() != '':
						self.serialconnected = True
						self.pushButton_connect.setText("Connected")
						self.timer.start()
						if self.time_old == "":
							self.time_old = time.time()
						print([self.limits.port_set], baudrate, slave_addr)
						self.pushButton_CSV_view.setEnabled(False)		# disable CSV viewing capability
						self.pushButton_clear_plot_clicked()			# clear plot
				except (OSError, serial.SerialException) as detail1:
					print(datetime.datetime.now().strftime("%y-%m-%d %H:%M:%S"), "Error1 - ", detail1)
					pass

		except Exception as detail:
			print(datetime.datetime.now().strftime("%y-%m-%d %H:%M:%S"), "Error - ", detail)
			self.serial_disconnect("Try again !!!")
		
	def serial_disconnect(self, status):
		self.shutdown()
		self.serialconnected = False
		self.mutex.unlock()
		self.timer.stop()
		self.pushButton_connect.setText(status)
		self.pushButton_connect.setChecked(False)
		self.combobox_populate()
		self.pushButton_CSV_view.setEnabled(True)						# enable CSV viewing capability
		print(status)
			
app = QApplication(sys.argv)
widget = dps_GUI()
widget.show()

sys.exit(app.exec_())
	
