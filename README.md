# DPS5005_pyGUI
A python GUI to display &amp; control DPS5005 power supply

* Hardware: DPS5005
* Software: v1.6

Additional settings:
* hold 'up' arrow while powering on to access interface setup area. 
* Modbus unit ID, baud rate, BT pin etc. 
* Press 'set' twice in succession to exit.
- note: baud rate 2400 & 19200 does not appear to work. 4800 & 9600 OK.
 
<img src="images/gui_screenshot_image.png">

Files:
* dps_GUI.ui         - QT designer v5.9.2
* dps_GUI_program.py - Python 2.7.14
* dps_modbus.py      - Python 2.7.14
* dps5005_limits.ini - text file

## dps_GUI.ui
## dps_GUI_program.py
## dps_modbus.py
## dps5005_limits.ini
