#!/usr/bin/python
###################################
# pyRoast - Coffee roasting profile
# (C) Andrew Tridgell 2009
# Released under GNU GPLv3 or later

from pyRoastUI import *
from PyKDE4.kdeui import KPlotObject
import threading, time, os, subprocess, signal, select, csv
from PyKDE4.kio import KFileDialog
from PyKDE4.kdecore import KUrl
from PyQt4.QtGui import QFileDialog

# a few constants
gTempArraySize = 5
gUpdateFrequency = 0.2
gPlotColor = QtGui.QColor(255, 128, 128)
gProfileColor = QtGui.QColor(10, 50, 255)
gMaxTime = 30.0
gMaxTemp = 300
gVersion = "0.1"

#############################
# current time in mm:ss form
def TimeString():
    elapsed = (time.time() - StartTime)/60.0
    return ("%2u:%02u" % (int(elapsed), (elapsed - int(elapsed))*60))
    

############################
# write a message to the msg
# window, prefixed by the time
def AddMessage(m):
    ui.tMessages.append(TimeString() + " " + m)

############################
# reset the plot
def bReset():
    global StartTime, CurrentTemperature, MaxTemperature
    StartTime = time.time()
    dmmPlot.clearPoints()
    CurrentTemperature = 0
    MaxTemperature = 0
    TemperatureArray = []
    ui.tMessages.setText("")
    ui.TemperaturePlot.update()

############################
# called when a roast event comes on
def bEvent(estring):
    global StartTime
    elapsed = (time.time() - StartTime)/60.0
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
# load an existing CSV
# as a profile plot
def bLoadProfile():
    global LoadedProfile
    filename = QFileDialog.getOpenFileName(pyRoast, "Profile File", "", "*.csv")
    if (filename == ""):
        return
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
    # kill off the meter reader child
    os.kill(dmm.pid, signal.SIGTERM)
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
    if (len(dmmPlot.points()) < 10):
        return 0
    y2 = dmmPlot.points()[-1].y()
    y1 = dmmPlot.points()[-10].y()
    x2 = dmmPlot.points()[-1].x()
    x1 = dmmPlot.points()[-10].x()
    if (x2 == x1):
        return 0
    return (y2-y1)/(x2-x1)

############################
# check for input from the DMM
def CheckDMMInput():
    global CurrentTemperature, MaxTemperature
    while (select.select([dmm.stdout], [], [], 0)[0]):
        line = dmm.stdout.readline().strip(" \n\r")
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
            if (len(TemperatureArray) >= gTempArraySize):
                del TemperatureArray[:1]
            TemperatureArray.append(temp)
            CurrentTemperature = sum(TemperatureArray) / len(TemperatureArray)
            if (CurrentTemperature > MaxTemperature):
                MaxTemperature = CurrentTemperature
            ui.tCurrentTemperature.setText("%.1f" % CurrentTemperature)
            ui.tMaxTemperature.setText("%.1f" % MaxTemperature)
            ui.tRateOfChange.setText(("%.1f" + u'\N{DEGREE SIGN}' + "C/m") % RateOfChange())
        except:
            AddMessage("Bad DMM digits %02x %02x %02x %02x" % (d1, d2, d3, d4))



############################
# called once a second
def tick():
    global CurrentTemperature, StartTime
    elapsed = (time.time() - StartTime)/60.0
    CheckDMMInput()
    if (CurrentTemperature != 0):
        dmmPlot.addPoint(elapsed, CurrentTemperature, "")
    ui.tElapsed.setText(TimeString());
    ui.TemperaturePlot.update()
    threading.Timer(gUpdateFrequency, tick).start()

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


############################################
# main program
if __name__ == "__main__":
    import sys
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

    # setup a one-second update
    threading.Timer(gUpdateFrequency, tick).start()

    # get the current time
    StartTime = time.time()
    TemperatureArray = []
    CurrentTemperature = 0.0
    MaxTemperature = 0.0

    # start the dmm child
    dmm = subprocess.Popen("../rmr.exe", stdout=subprocess.PIPE)

    # set a default file name
    ChooseDefaultFileName()

    AddMessage("Welcome to pyRoast " + gVersion);

    pyRoast.show()
    sys.exit(app.exec_())
