#!/usr/bin/python
###################################
# pyRoast - Coffee roasting profile
# (C) Andrew Tridgell 2009
# Released under GNU GPLv3 or later

from pyRoastUI import *
from PyKDE4.kdeui import KPlotObject
import time, os, subprocess, signal, select, csv
from PyKDE4.kio import KFileDialog
from PyKDE4.kdecore import KUrl
from PyQt4.QtGui import QFileDialog
import getopt, sys, serial, math

# a few constants
gTempArraySize = 5
gUpdateFrequency = 0.25
gPlotColor = QtGui.QColor(255, 128, 128)
gProfileColor = QtGui.QColor(10, 50, 255)
gMaxTime = 30.0
gMaxTemp = 300
gVersion = "0.1"
rmr = "./RawMeterReader"
simulate_temp = False
time_speedup = 1
pcontrol = None
pcontrol_dev = None
profile_file = None
verbose = False

PID_integral = 0
PID_previous_error = 0
PID_lastt = 0
PID_Kp = 0.5
PID_Ki = 2
PID_Kd = 0.8
current_power = 100

sim_last_time = 0
sim_last_temp = 0
sim_base_temp = 29.0

######################
# get the elapsed time
def ElapsedTime():
    global StartTime
    return time_speedup*(time.time() - StartTime)

#############################
# current time in mm:ss form
def TimeString():
    elapsed = ElapsedTime()/60.0
    return ("%2u:%02u" % (int(elapsed), (elapsed - int(elapsed))*60))
    

############################
# write a message to the msg
# window, prefixed by the time
def AddMessage(m):
    ui.tMessages.append(TimeString() + " " + m)

def DebugMessage(m):
    global verbose
    if (verbose):
        AddMessage(m)

############################
# reset the plot
def bReset():
    global StartTime, CurrentTemperature, MaxTemperature, sim_last_time, TemperatureArray
    StartTime = time.time()
    sim_last_time = 0
    dmmPlot.clearPoints()
    CurrentTemperature = 0
    MaxTemperature = 0
    TemperatureArray = []
    ui.tMessages.setText("")
    ui.TemperaturePlot.update()

############################
# called when a roast event comes on
def bEvent(estring):
    elapsed = ElapsedTime()/60.0
    dmmPlot.addPoint(elapsed, CurrentTemperature, estring)
    AddMessage(estring)

def bFirstCrack():
    bEvent("First crack")

def bRollingFirstCrack():
    bEvent("Rolling first crack")

def bSecondCrack():
    bEvent("Second crack")

def bRollingSecondCrack():
    bEvent("Rolling second crack")

def bUnload():
    bEvent("Unload")

###########################
# useful fn to see if a string
# is a number
def isNumber(s):
    try:
        v = float(s)
    except:
        return False
    return True

###########################
# work out the profile temperature
# given a time
def ProfileTemperature():
    global LoadedProfile
    elapsed = ElapsedTime()/60.0
    points = LoadedProfile.points()
    for p in points:
        if (p.x() >= elapsed):
            return p.y()
    return 0.0

###########################
# load an existing CSV
# as a profile plot
def LoadProfile(filename):
    global LoadedProfile
    reader = csv.reader(open(filename))
    LoadedProfile.clearPoints()
    for p in reader:
        if (isNumber(p[0])):
            label = p[2]
            if (isNumber(label)):
                label = ""
            LoadedProfile.addPoint(float(p[0])/60.0, float(p[1]), label);
    ui.TemperaturePlot.update()

###########################
# load a profile via GUI
def bLoadProfile():
    global LoadedProfile
    filename = QFileDialog.getOpenFileName(pyRoast, "Profile File", "", "*.csv")
    if (filename == ""):
        return
    LoadProfile(filename)
    
###########################
# save the data
def bSave():
    points = dmmPlot.points()
    fname = str(ui.tFileName.text());
    if (fname == ""):
        AddMessage("Please choose a file name")
        return
    if (fname.find('.') == -1):
        fname += ".csv";
    f = open(fname, 'w')
    AddMessage("Saving %u points to \"%s\"" % (len(points), fname))
    f.write("Time,Temperature,Event\n");
    for p in points:
        f.write("%f,%f,\"%s\"\n" % (p.x()*60.0, p.y(), p.label()))
    f.close()

#############################
# save using a file dialog
def bSaveAs():
    filename = QFileDialog.getOpenFileName(pyRoast, "Profile File", "", "*.csv")
    if (filename):
        #filename = os.path.relpath(filename)
        filename = str(filename)
        if (os.path.dirname(filename) == os.path.realpath(os.curdir)):
            filename = os.path.basename(filename)
        ui.tFileName.setText(filename)
        bSave()

###############
# shutdown
def bQuit():
    global pcontrol
    # kill off the meter reader child
    if (not simulate_temp):
        os.kill(dmm.pid, signal.SIGTERM)
    if (pcontrol is not None):
        pcontrol.write("0%\r\n")
        pcontrol.setDTR(0)
    pyRoast.close()

################
# setup the plot
# parameters
def SetupPlot(plot, dmmPlot, profile):
    plot.setLimits(0.0, gMaxTime, 0.0, gMaxTemp)
    plot.axis(0).setLabel("Temperature (" + u'\N{DEGREE SIGN}' + "C)")
    plot.axis(1).setLabel("Time (minutes)")
    plot.addPlotObject(dmmPlot)
    plot.addPlotObject(profile)

###################################
# get the target temperature
def GetTarget():
    if (ui.vTarget.value() != 0):
        return ui.vTarget.value()
    return ProfileTemperature()

###################################
# adjust the amount of power to the heat gun 
def PowerControl():
    global CurrentTemperature, current_power
    global pcontrol

    current = CurrentTemperature
    target = GetTarget()
    elapsed = ElapsedTime()/60.0
    dt = elapsed - PID_lastt
    # don't change the power level more than once every 2 seconds

    if (dt < 2/60.0):
        return
    
    error = target - CurrentTemperature
    roc = RateOfChange()

    power = current_power
    # predict the temperature 30 seconds
    predict = error - (2*roc)
    power = power + (predict/60)
        
    if (power > 100):
        power = 100
    elif (power < 0):
        power = 0

    if (not ui.cAutoPower.isChecked()):
        power = ui.sPowerSlider.value()
    if (int(power) != int(current_power)):
        AddMessage("power => " + str(int(power)))
    if (pcontrol is not None):
        spower = power
        # there seems to be a bug in the power controller for 100% power
        if (spower > 99):
            spower = 99
        pcontrol.setDTR(1)
        pcontrol.write("%u%%\r\n" % int(spower))
    current_power = power
    ui.tPower.clear()
    ui.tPower.setText("%3u%%" % current_power)
    ui.sPowerSlider.setValue(current_power)


def PID_PowerControl():
    global CurrentTemperature, PID_integral, PID_previous_error, current_power
    global PID_lastt, pcontrol

    current = CurrentTemperature
    target = GetTarget()
    elapsed = ElapsedTime()/60.0
    dt = elapsed - PID_lastt
    # don't change the power level more than once every 2 seconds

    if (dt < 2/60.0):
        return
    
    error = target - CurrentTemperature
    PID_integral = PID_integral + (error*dt)
    derivative = (error - PID_previous_error)/dt
    output = (PID_Kp*error) + (PID_Ki*PID_integral) + (PID_Kd*derivative)
#    AddMessage("dt=%f Kp_term=%f Ki_term=%f Kd_term=%f" % (dt,PID_Kp*error,PID_Ki*PID_integral,PID_Kd*derivative))
    PID_previous_error = error
    PID_lastt = elapsed

    # decay the integral component over 1 minute to 10%
    decay = math.exp(dt*math.log(0.1))
    PID_integral = PID_integral * decay
    

    # map output into power level.
    # testing shows that 50% means keep at current temp
    power = int(output + current_power)
    if (power > 100):
        power = 100
    elif (power < 0):
        power = 0

    if (ui.cAutoPower.isChecked()):
        DebugMessage("current=%f target=%f PID Output %f power=%f" % (current, target, output, power))
    else:
        power = ui.sPowerSlider.value()
    if (power != current_power):
        AddMessage("setting power to " + str(power))
    if (pcontrol is not None):
        spower = power
        pcontrol.setDTR(1)
        pcontrol.write("%u%%\r\n" % spower)
    current_power = power
    ui.tPower.clear()
    ui.tPower.setText("%3u%%" % current_power)
    ui.sPowerSlider.setValue(current_power)



####################
# called when we get a temp value
def GotTemperature(temp):
    global CurrentTemperature, MaxTemperature, TemperatureArray
    if (len(TemperatureArray) >= gTempArraySize):
        del TemperatureArray[:1]
    if (temp <= 0.0):
        return
    TemperatureArray.append(temp)
    CurrentTemperature = sum(TemperatureArray) / len(TemperatureArray)
    if (CurrentTemperature > MaxTemperature):
        MaxTemperature = CurrentTemperature
    ui.tCurrentTemperature.setText("%.1f" % CurrentTemperature)
    ui.tMaxTemperature.setText("%.1f" % MaxTemperature)
    ui.tRateOfChange.setText(("%.1f" + u'\N{DEGREE SIGN}' + "C/m") % RateOfChange())
    PowerControl()
                
#################################
# map the strange hex formatted
# DMM digits for a Victor 86B DMM
# to a normal digit
def MapDigit(d):
    digitMap = {
        0x03 : '2',
        0x04 : '2',
        0x05 : '2',
        0x25 : '9',
        0x26 : '9',
        0x27 : '9',
        0x2D : '5',
        0x2E : '5',
        0x2F : '5',
        0x41 : '0',
        0x42 : '0',
        0x43 : '0',
        0x45 : '8',
        0x46 : '8',
        0x47 : '8',
        0x4D : '6',
        0x4E : '6',
        0x4F : '6',
        0x60 : '1',
        0x61 : '1',
        0x62 : '1',
        0xA4 : '4',
        0xA5 : '4',
        0xA6 : '4',
        0xE0 : '7',
        0xE1 : '7',
        0xE2 : '7',
        0xE5 : '3',
        0xE6 : '3',
        0xE7 : '3'}

    ret = ""
    if (d & 0x10):
        ret += "."
    if (not digitMap[d & 0xEF]):
        AddMessage("Bad digit: %02x" % d)
        
    ret += digitMap[d & 0xEF]
    return ret

############################
# work out the rate of change
# of the temperature
def RateOfChange():
    points = dmmPlot.points()
    numpoints = len(points)
    if (numpoints < 10):
        return 0
    x1 = 0
    x2 = points[-1].x()
    y2 = points[-1].y()
    for i in range(2,numpoints-2):
        if (x2 - points[-i].x() > 5.0/60):
            x1 = points[-i].x()
            y1 = points[-i].y()
            break;
    if (x1 == 0):
        return 0
    
    return (y2-y1)/(x2-x1)

def DeltaT(T, P, Tbase):
    r=0.0085
    k=0.0040
    return r*P - k*(T-Tbase)

############################
# simulate temperature profile
def SimulateTemperature():
    global sim_last_time, sim_base_temp, current_power
    global TempCells, NumCells
    if (sim_last_time == 0):
        sim_last_time = ElapsedTime()
        GotTemperature(sim_last_temp)
        TempCells = {}
        NumCells = 40
        for i in range(0, NumCells):
            TempCells[i] = sim_base_temp
        return

    t = ElapsedTime()
    elapsed = (t - sim_last_time)
    # the CS DMM gives a value every 0.5 seconds
    if (elapsed < 0.5):
        return

    sim_last_time = t

    TempCells[0] += DeltaT(TempCells[0], current_power, sim_base_temp) * elapsed
    for i in range(1, NumCells):
        TempCells[i] = (TempCells[i-1] + TempCells[i])/2
        
    GotTemperature(TempCells[NumCells-1])


############################
# simulate temperature profile
def OLD_SimulateTemperature():
    global sim_last_time, sim_last_temp, sim_base_temp
    global PowerArray, PowerArraySize;
    if (sim_last_time == 0):
        sim_last_time = ElapsedTime()
        sim_last_temp = sim_base_temp
        GotTemperature(sim_last_temp)
        PowerArray = {};
        PowerArraySize = 50
        return
    t = ElapsedTime()
    ielapsed = int(t)
    elapsed = (t - sim_last_time)
    # the CS DMM gives a value every 0.5 seconds
    if (elapsed < 0.5):
        return
    sim_last_time = t
    PowerArray[str(ielapsed)] = current_power;
    if (PowerArray.has_key(str(ielapsed-PowerArraySize))):
        del PowerArray[str(ielapsed-PowerArraySize)]
    power = 0
    count = 0
    for i in range(0,PowerArraySize):
        if (PowerArray.has_key(str(ielapsed-i))):
            power += PowerArray[str(ielapsed-i)]
            count = count + 1
    power = power / count
    sim_last_temp += DeltaT(sim_last_temp, power, sim_base_temp) * elapsed
    DebugMessage(("sim_last_temp=%.2f current_power=%.2f sim_base_temp=%.2f elapsed=%.2f DeltaT=%.2f" % (sim_last_temp, current_power, sim_base_temp, elapsed, DeltaT(sim_last_temp, power, sim_base_temp))))
    GotTemperature(sim_last_temp)


############################
# check for input from the DMM
def CheckDMMInput():
    global CurrentTemperature, MaxTemperature
    if (simulate_temp):
        SimulateTemperature()
        return
    while (select.select([dmm_file], [], [], 0)[0]):
        line = dmm_file.readline().strip(" \n\r")
        s = line.split(" ")
            
        if len(s) != 15:
            AddMessage("Invalid DMM data: " + line)
            return
        if (s[12] != "BF" or s[13] != "6E" or s[14] != "6C"):
            AddMessage("DMM not in temperature mode: " + line)
            return

        # oh what a strange format the data is in ...
        d1 = int(s[11][0] + s[4][0], 16)
        d2 = int(s[10][0] + s[7][0], 16)
        d3 = int(s[8][0]  + s[6][0], 16)
        d4 = int(s[1][0]  + s[3][0], 16)
        d3 ^= 0x10
        try:
            temp = float(MapDigit(d1) + MapDigit(d2) + MapDigit(d3) + MapDigit(d4))
            GotTemperature(temp)

        except:
            AddMessage("Bad DMM digits %02x %02x %02x %02x" % (d1, d2, d3, d4))


############################
# called once a second
def tick():
    global CurrentTemperature
    elapsed = (ElapsedTime())/60.0
    CheckDMMInput()
    if (CurrentTemperature != 0):
        dmmPlot.addPoint(elapsed, CurrentTemperature, "")
    ui.tElapsed.setText(TimeString());
    ui.TemperaturePlot.update()

#############################
# choose a reasonable default
# file name
def ChooseDefaultFileName():
    fname = time.strftime("%Y%m%d") + ".csv";
    i=1
    while (os.path.exists(fname)):
       i = i+1
       fname = time.strftime("%Y%m%d") + "-" + str(i) + ".csv";
    ui.tFileName.setText(fname)

############################
# open a serial port for 
# power control
def PcontrolOpen(file):
    s = serial.Serial(file, 9600, parity='N', rtscts=False, 
                      xonxoff=False, timeout=1.0)
    time.sleep(0.2)
    s.setDTR(1)
    return s


#############################
def usage():
    print """
Usage: pyRoast.py [options]
Options:
  -h                   show this help
  --verbose	       verbose messages
  --simulate	       simulate temperature readings
  --profile PROFILE    preload a profile
  --pcontrol FILE      send PID power control to FILE
  --smooth N	       smooth temperature over N values
"""
    

############################################
# main program
if __name__ == "__main__":
    import sys

    try:
        opts, args = getopt.getopt(sys.argv[1:], "h",
                                   ["help", "smooth=", "pcontrol=",
                                    "profile=", "simulate", "verbose",
                                    "speedup=","maxtemp=","maxtime="])
    except getopt.GetoptError, err:
        print str(err)
        usage()
        sys.exit(2)

    for o,a in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit(1)
        elif o in ("--verbose"):
            verbose = True
        elif o in ("--simulate"):
            simulate_temp = True
        elif o in ("--speedup"):
            time_speedup = int(a)
        elif o in ("--maxtemp"):
            gMaxTemp = int(a)
        elif o in ("--maxtime"):
            gMaxTime = int(a)
        elif o in ("--smooth"):
            gTempArraySize = int(a)
        elif o in ("--profile"):
            profile_file = a
        elif o in ("--pcontrol"):
            pcontrol_dev = a
        else:
            assert False, "unhandled option"

    app = QtGui.QApplication(sys.argv)
    pyRoast = QtGui.QMainWindow()
    ui = Ui_pyRoast()
    ui.setupUi(pyRoast)

    # create plot of multimeter
    dmmPlot = KPlotObject(gPlotColor, KPlotObject.Lines,
                          6, KPlotObject.Circle)
    LoadedProfile = KPlotObject(gProfileColor, KPlotObject.Lines,
                                6)
    SetupPlot(ui.TemperaturePlot, dmmPlot, LoadedProfile)

    pyRoast.setWindowTitle("pyRoast")
    
    # connect up the buttons
    QtCore.QObject.connect(ui.bQuit, QtCore.SIGNAL("clicked()"), bQuit)
    QtCore.QObject.connect(ui.bSave, QtCore.SIGNAL("clicked()"), bSave)
    QtCore.QObject.connect(ui.bSaveAs, QtCore.SIGNAL("clicked()"), bSaveAs)
    QtCore.QObject.connect(ui.bReset, QtCore.SIGNAL("clicked()"), bReset)
    QtCore.QObject.connect(ui.bLoadProfile, QtCore.SIGNAL("clicked()"), bLoadProfile)
    QtCore.QObject.connect(ui.bFirstCrack, QtCore.SIGNAL("clicked()"), bFirstCrack)
    QtCore.QObject.connect(ui.bRollingFirstCrack,
                           QtCore.SIGNAL("clicked()"), bRollingFirstCrack)
    QtCore.QObject.connect(ui.bSecondCrack, QtCore.SIGNAL("clicked()"), bSecondCrack)
    QtCore.QObject.connect(ui.bRollingSecondCrack,
                           QtCore.SIGNAL("clicked()"), bRollingSecondCrack)
    QtCore.QObject.connect(ui.bUnload, QtCore.SIGNAL("clicked()"), bUnload)

    ctimer = QtCore.QTimer()
    QtCore.QObject.connect(ctimer, QtCore.SIGNAL("timeout()"), tick)
    ctimer.start(int((1000 * gUpdateFrequency) / time_speedup))
    
    # get the current time
    StartTime = time.time()
    TemperatureArray = []
    CurrentTemperature = 0.0
    MaxTemperature = 0.0
    current_power = 0
    
    ui.tPower.setText("%3u%%" % current_power)
    ui.sPowerSlider.setValue(current_power)
    ui.cAutoPower.setChecked(True)
    # start the dmm child
    if (not simulate_temp):
        dmm = subprocess.Popen(rmr, stdout=subprocess.PIPE)
        dmm_file = dmm.stdout

    if (pcontrol_dev is not None):
        AddMessage("opening power control " + pcontrol_dev);
        pcontrol = PcontrolOpen(pcontrol_dev)

    # set a default file name
    ChooseDefaultFileName()

    ui.CSLogo.setPixmap(QtGui.QPixmap('cslogo.png'))

    if (profile_file is not None):
        LoadProfile(profile_file)

    AddMessage("Welcome to pyRoast " + gVersion);

    pyRoast.show()
    sys.exit(app.exec_())
