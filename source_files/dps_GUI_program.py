import traceback, sys
import subprocess
import glob
import serial
import time
import os
import csv
import datetime

from dps_modbus import Serial_modbus
from dps_modbus import Dps5005
from dps_modbus import Import_limits

from PyQt5.QtCore import pyqtSlot, pyqtSignal, QRunnable, QThreadPool, QTimer, QThread, QCoreApplication, QObject, QMutex
from PyQt5.QtWidgets import QApplication, QMainWindow, QSlider, QAction, QFileDialog, QGraphicsView
from PyQt5.QtGui import QIcon
from PyQt5.uic import loadUi

import pyqtgraph as pg
from pyqtgraph import PlotWidget, GraphicsLayoutWidget
import numpy as np

mutex = QMutex()
dps = 0

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
		super(dps_GUI,self).__init__()
		loadUi('dps_GUI.ui', self)
		self.setWindowTitle('DPS5005')
		
	#--- threading
		self.threadpool = QThreadPool()
	#	print("Multithreading with maximum %d threads" % self.threadpool.maxThreadCount())
		
	#--- globals
		self.serialconnected = False
		self.slider_in_use = False
		self.initial_state = True
		self.CSV_file = ''
		self.CSV_list = []
		self.graph_X = []
		self.graph_Y1 = []
		self.graph_Y2 = []
		self.time_old = time.time()
		
	#--- PlotWidget
		self.pg_plot_setup()
			
	#--- connect signals
		self.pushButton_save_plot.clicked.connect(self.pushButton_save_plot_clicked)
		self.pushButton_clear.clicked.connect(self.pushButton_clear_clicked)
	
		self.radioButton_lock.toggled.connect(self.radioButton_lock_clicked)
		self.pushButton_onoff.clicked.connect(self.pushButton_onoff_clicked)
		self.pushButton_set.clicked.connect(self.pushButton_set_clicked)
		self.pushButton_connect.clicked.connect(self.pushButton_connect_clicked)
		
		self.pushButton_CSV.clicked.connect(self.pushButton_CSV_clicked)
		self.pushButton_CSV_clear.clicked.connect(self.pushButton_CSV_clear_clicked)
				
		self.horizontalSlider_brightness.sliderReleased.connect(self.horizontalSlider_brightness_sliderReleased)
		self.horizontalSlider_brightness.sliderPressed.connect(self.horizontalSlider_brightness_sliderPressed)
		self.actionOpen.triggered.connect(self.file_open)
		self.actionExit.triggered.connect(self.close)
		
	#--- do once on startup
		self.combobox_populate()

	#--- setup & run background task
		self.timer2 = QTimer()
		self.timer2.setInterval(10)
		self.timer2.timeout.connect(self.action_CSV)
		
		self.timer = QTimer()
		self.timer.setInterval(1000)
		self.timer.timeout.connect(self.read_all)

	def pg_plot_setup(self): # right axis not connected to automatic scaling on the left, 'A' icon on bottom LHD
		self.p1 = self.graphicsView.plotItem
		self.p1.setClipToView(True)		
		
	# x axis	
		self.p1.setLabel('bottom', 'Time', units='s', color='g', **{'font-size':'10pt'})
		self.p1.getAxis('bottom').setPen(pg.mkPen(color='g', width=1))
	
	# Y1 axis	
		self.p1.setLabel('left', 'Voltage', units='V', color='r', **{'font-size':'10pt'})
		self.p1.getAxis('left').setPen(pg.mkPen(color='r', width=1))
	
	# setup viewbox for right hand axis
		self.p2 = pg.ViewBox()
		self.p1.showAxis('right')
		self.p1.scene().addItem(self.p2)
		self.p1.getAxis('right').linkToView(self.p2)
		self.p2.setXLink(self.p1)

	# Y2 axis
		self.p1.setLabel('right', 'Current', units="A", color='c', **{'font-size':'10pt'})
		self.p1.getAxis('right').setPen(pg.mkPen(color='c', width=1))
		
	# scales ViewBox to scene
		self.p1.vb.sigResized.connect(self.updateViews)	
		
	def updateViews(self):
		self.p2.setGeometry(self.p1.vb.sceneBoundingRect())
		self.p2.linkedViewChanged(self.p1.vb, self.p2.XAxis)

#--- update graph
	def update_graph_plot(self):
		start = time.time()	
		X = np.asarray(self.graph_X, dtype=np.float32)
		Y1 = np.asarray(self.graph_Y1, dtype=np.float32)
		Y2 = np.asarray(self.graph_Y2, dtype=np.float32)
	
		pen1=pg.mkPen(color='r',width=1.0)
		pen2=pg.mkPen(color='c',width=1.0)

		self.p1.clear()
		self.p2.clear()
		
		self.p1.plot(X,Y1,pen=pen1, name="V")
		self.p2.addItem(pg.PlotCurveItem(X,Y2,pen=pen2, name="I"))

		app.processEvents()
		
		a = (time.time() - start) * 1000.0
		self.label_plot_rate.setText(("Plot Rate  : %6.3fms" % (a)))

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
			with open(filename, 'w') as f:
				writer = csv.writer(f)
				row = ['time(s)','voltage(V)','current(A)']
				writer.writerow(row)
				for row in rows:
					writer.writerow(row)
		
#--- thread related code
	def progress_fn(self, n):
		print("%d%% done" % n)
		
	def print_output(self, s):
		print(s)
		
	def thread_complete(self):
		print("THREAD COMPLETE!")
	
#--- buttons
	def pushButton_save_plot_clicked(self):
		self.file_save()

	def pushButton_clear_clicked(self):	
		self.graph_X = []
		self.graph_Y1 = []
		self.graph_Y2 = []
		self.time_old = time.time()
		self.p1.clear()
		self.p2.clear()
		
	def radioButton_lock_clicked(self):
		if self.radioButton_lock.isChecked():
			value = 1
		else:
			value = 0
		self.pass_2_dps('lock', 'w', str(value))

	def pushButton_onoff_clicked(self):
		if self.pushButton_onoff.isChecked():
			value = 1
			self.pushButton_onoff.setText("ON")
		else:
			value = 0
			self.pushButton_onoff.setText("OFF")
		self.pass_2_dps('onoff', 'w', str(value))
	
	def pushButton_set_clicked(self):
		if self.lineEdit_vset.text() != '' or self.lineEdit_iset.text() != '':
			try:
				value1 = float(self.lineEdit_vset.text())
			except ValueError:
				self.lineEdit_vset.setText("Type a number!!")
				return
			try:
				value2 = float(self.lineEdit_iset.text())
			except ValueError:
				self.lineEdit_iset.setText("Type a number!!")
				return
			self.pass_2_dps('write_voltage_current', 'w', [value1, value2])
	
	def pushButton_connect_clicked(self):
		if self.pushButton_connect.isChecked():
			self.serial_connect()
			self.initial_state = True
		else:
			self.serial_disconnect()
	
	def pushButton_CSV_clicked(self):
		if self.CSV_list != '':
			self.action_CSV()
	
	def pushButton_CSV_clear_clicked(self):
		self.CSV_list = []
		self.timer2.stop()
		self.label_CSV.setText("Steps remaining: %2d" % len(self.CSV_list))
		
	def open_CSV(self, filename):
		with open(filename, 'r') as f:
			csvReader = csv.reader(f)#, delimiter=',')	# reads file
			next(csvReader, None)						# skips header
			data_list = list(csvReader)
			self.CSV_list = data_list
		self.labelCSV(len(self.CSV_list))	
				
	def labelCSV(self, value):
		self.label_CSV.setText("Steps remaining: %2d" % value)
		
	def action_CSV(self):
		if self.pushButton_onoff.isChecked() == True:	
			if len(self.CSV_list) > 0:
				self.label_CSV.setText("Steps remaining: %2d" % len(self.CSV_list))
				data_list = self.CSV_list
				
				if len(self.CSV_list) > 1:
					value0 = float(data_list[1][0]) - float(data_list[0][0])
				else:
					value0 = 0
				value1 = float(data_list[0][1])
				value2 = float(data_list[0][2])
				
				self.pass_2_dps('write_voltage_current', 'w', [value1, value2])
				
				data_list.pop(0)
				self.timer2.stop()
				self.timer2.setInterval(value0*1000)
				self.timer2.start()
				self.label_CSV.setText("Steps remaining: %2d" % len(self.CSV_list))
			else:
				self.timer2.stop()
		
#--- slider	
	def horizontalSlider_brightness_sliderPressed(self):
		self.slider_in_use = True
		
	def horizontalSlider_brightness_sliderReleased(self):
		self.pass_2_thread(self.slider_change)
		self.slider_in_use = False
		
	def slider_change(self, progress_callback):
		value = self.horizontalSlider_brightness.value()
		self.pass_2_dps('b_led', 'w', str(value))
		self.label_brightness.setText('Brightness Level: %s' % value)

#--- thread the needle	
	def pass_2_thread(self, func):
		# Pass the function to execute
		worker = Worker(func) # Any other args, kwargs are passed to the run function
		worker.signals.result.connect(self.print_output)
		worker.signals.finished.connect(self.thread_complete)
		worker.signals.progress.connect(self.progress_fn)
		self.threadpool.start(worker)

	def update_values_fast(self, progress_callback):	
		self.refresh_all()
		progress_callback.emit(1)

#--- read & display values from DPS		
	def read_all(self):
		start = time.time()
		data = self.pass_2_dps('read_all')
		if data != False:		
			self.vout = ("%5.2f" % data[2])	# vout
			self.iout = ("%5.3f" % data[3])	# iout
			
			self.time_interval = time.time() - self.time_old
			#print self.time_interval
						
			self.graph_X.append(self.time_interval)#len(self.graph_Y1))
			self.graph_Y1.append(self.vout)
			self.graph_Y2.append(self.iout)
			
			self.update_graph_plot()
			
			self.lcdNumber_vset.display("%5.2f" % data[0])	# vset
			self.lcdNumber_iset.display("%5.3f" % data[1])	# iset
			self.lcdNumber_vout.display(self.vout)	# vout
			self.lcdNumber_iout.display(self.iout)	# iout
			
			self.lcdNumber_pout.display("%5.2f" % data[4])	# power
			self.lcdNumber_vin.display("%5.2f" % data[5])		# vin
		# lock
			value = data[6]
			if value == 1 and self.radioButton_lock.isChecked() == True:
				pass
			elif value == 1 and self.radioButton_lock.isChecked() == False:	
				self.radioButton_lock.setChecked(True)
				self.radioButton_lock_clicked()
			elif value == 0 and self.radioButton_lock.isChecked() == True:	
				self.radioButton_lock.setChecked(False)
				self.radioButton_lock_clicked()
			elif value == 0 and self.radioButton_lock.isChecked() == False:
				pass
				
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
			if value == 1 and self.pushButton_onoff.isChecked() == True:
				self.label_onoff.setText('Output      :   ON')	# on/off
			elif value == 1 and self.pushButton_onoff.isChecked() == False:	
				self.label_onoff.setText('Output      :   ON')	# on/off
				self.pushButton_onoff.setChecked(True)
				self.pushButton_onoff_clicked()
			elif value == 0 and self.pushButton_onoff.isChecked() == True:	
				self.label_onoff.setText('Output      :   OFF')	# on/off
				self.pushButton_onoff.setChecked(False)
				self.pushButton_onoff_clicked()
			elif value == 0 and self.pushButton_onoff.isChecked() == False:
				self.label_onoff.setText('Output      :   OFF')	# on/off
		# slider	
			if self.slider_in_use == False:							# update when not in use
				value = int(data[10])
				self.horizontalSlider_brightness.setValue(value)	# brightness
				self.label_brightness.setText('Brightness Level:   %s' % value)
			self.label_model.setText("Model       :   %s" % data[11])	# model
			
			self.label_version.setText("Version     :   %s" % data[12])	# version
	#		self.lcdNumber_iout.display(data[13])	# extract_m
	#		self.lcdNumber_iout.display(data[14])	# iout
	#		self.lcdNumber_iout.display(data[15])	# iout
		a = (time.time() - start) * 1000.0
		self.label_data_rate.setText("Data Rate : %6.3fms" % a)
	      
	def combobox_ports_read(self):
		return self.comboBox_ports.currentText()
	
	def combobox_datarate_read(self):
		return self.comboBox_datarate.currentText()
				    
	def combobox_populate(self):		# collects info on startup
		self.comboBox_ports.clear()
		self.comboBox_ports.addItems(self.serial_ports())
		
		self.comboBox_datarate.clear()
		self.comboBox_datarate.addItems(["9600", "2400", "4800", "19200"])	# note: 2400 & 19200 doesn't seem to work

	def pass_2_dps(self, function, cmd = "r", value = 0):
		if self.serialconnected != False:
			mutex.lock()
			a = eval("dps.%s('%s', %s)" % (function, cmd, value))
			mutex.unlock()
			return(a)
		return False

#--- serial port stuff	
	def serial_ports(self):
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
				s.close()
				result.append(port)
			except (OSError, serial.SerialException):
				pass
		return result
		
	def serial_connect(self):
		port = str(self.combobox_ports_read())
		baudrate = int(self.combobox_datarate_read())
		slave_addr = int(self.lineEdit_slave_addr.text())
		try:
			limits = Import_limits("dps5005_limits.ini")
			ser = Serial_modbus(port, slave_addr, baudrate, 8)
			global dps
			dps = Dps5005(ser, limits) #'/dev/ttyUSB0', 1, 9600, 8)
			if dps.version() != '':
				self.serialconnected = True
				self.lineEdit_info.setText("Connected")
				self.timer.start()
		except Exception as detail:
			print datetime.datetime.now().strftime("%y-%m-%d %H:%M:%S"), "Error ", detail
			self.serialconnected = False
			self.lineEdit_info.setText("Try again !!!")
			self.pushButton_connect.setChecked(False)
		
	def serial_disconnect(self):
		self.serialconnected = False
		self.timer.stop()
		self.lineEdit_info.setText("Disconnected")

app = QApplication(sys.argv)
widget = dps_GUI()
widget.show()

sys.exit(app.exec_())
	
