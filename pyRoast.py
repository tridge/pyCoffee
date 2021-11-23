#!/usr/bin/env python3

import csv
import getopt
import math
import os
import signal
import subprocess
import time

import matplotlib.lines
import select
import serial

###################################
# pyRoast - Coffee roasting profile
# (C) Andrew Tridgell 2009
# Released under GNU GPLv3 or later

from pyRoastUI import *

# a few constants
gTempArraySize = 5
gUpdateFrequency = 0.25
gMaxTime = 30.0
gMaxTemp = 300
gVersion = "0.1"
rmr = "./RawMeterReader"
simulate_temp = False
nodmm = False
time_speedup = 1
pcontrol = None
pcontrol_dev = None
profile_file = None
temp2_dev = None
temp2 = None
verbose = False
dmmPlot: matplotlib.lines.Line2D = None
LoadedProfile: matplotlib.lines.Line2D = None

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
    return time_speedup * (time.time() - StartTime)


#############################
# current time in mm:ss form
def TimeString():
    elapsed = ElapsedTime() / 60.0
    return f"{int(elapsed):02g}:{(elapsed - int(elapsed)) * 60:02.0f}"


############################
# write a message to the msg
# window, prefixed by the time
def AddMessage(m):
    ui.temp_readout.write(f"{TimeString()} {m}\n")


def DebugMessage(m):
    global verbose
    if verbose:
        AddMessage(m)


############################
# reset the plot
# noinspection PyUnusedLocal
def bReset(event):
    global StartTime, CurrentTemperature, MaxTemperature, sim_last_time, TemperatureArray
    StartTime = time.time()
    sim_last_time = 0
    dmmPlot.set_data([], [])
    CurrentTemperature = 0
    MaxTemperature = 0
    TemperatureArray = []
    ui.temp_readout.SetValue("")
    ui.temperature_plot.draw()


############################
# called when a roast event comes on
def bEvent(estring):
    elapsed = ElapsedTime() / 60.0
    prev_annotations = ui.temperature_plot.axes.texts
    ytext = CurrentTemperature + 50
    if len(prev_annotations) > 0:
        prev_anno = prev_annotations[-1]
        if abs(ytext - prev_anno.xyann[1]) < 15:
            ytext = ytext + 15
    ui.temperature_plot.axes.annotate(estring, xy=(elapsed, CurrentTemperature), xytext=(elapsed + 1, ytext),
                                      arrowprops=dict(facecolor='black', shrink=0.05, width=0.5, headwidth=2.5,
                                                      alpha=0.7), )
    AddMessage(estring)


# noinspection PyUnusedLocal
def bFirstCrack(event):
    bEvent("First crack")


# noinspection PyUnusedLocal
def bRollingFirstCrack(event):
    bEvent("Rolling first crack")


# noinspection PyUnusedLocal
def bSecondCrack(event):
    bEvent("Second crack")


# noinspection PyUnusedLocal
def bRollingSecondCrack(event):
    bEvent("Rolling second crack")


# noinspection PyUnusedLocal
def bUnload(event):
    bEvent("Unload")


###########################
# useful fn to see if a string
# is a number
# noinspection PyUnusedLocal
def isNumber(s) -> bool:
    try:
        v = float(s)
    except ValueError:
        return False
    return True


###########################
# work out the profile temperature
# given a time
def ProfileTemperature() -> float:
    global LoadedProfile
    elapsed = ElapsedTime() / 60.0
    points = LoadedProfile.get_data()
    if len(points[1]) > 0:
        for p in points[1]:
            if p[0] >= elapsed:
                return p[1]
    return 0.0


###########################
# load an existing CSV
# as a profile plot
# noinspection PyUnusedLocal
def LoadProfile(filename):
    # TODO understand use of label variable.
    global LoadedProfile
    reader = csv.reader(open(filename))
    newx = []
    newy = []
    for p in reader:
        if isNumber(p[0]):
            label = p[2]
            if isNumber(label):
                label = ""
            newx.append(float(p[0]) / 60.0)
            newy.append(float(p[1]))
            # LoadedProfile.addPoint(float(p[0]) / 60.0, float(p[1]), label)
    LoadedProfile.set_data(newx, newy)
    ui.temperature_plot.draw()


###########################
# load a profile via GUI
# noinspection PyUnusedLocal
def bLoadProfile(event):
    global LoadedProfile
    openFileDialog = wx.FileDialog(ui, "Open", "", "",
                                   "Profile files (*.csv)|*.csv",
                                   wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
    button_pressed = openFileDialog.ShowModal()
    if button_pressed == wx.ID_CANCEL:
        return
    filename = openFileDialog.GetPath()
    if filename == "":
        return
    LoadProfile(filename)


###########################
# save the data
# noinspection PyUnusedLocal
def bSave(event):
    points = dmmPlot.get_data()
    points = list(zip(points[0], points[1]))
    fname = str(ui.file_entry_box.GetValue())
    if fname == "":
        AddMessage("Please choose a file name")
        return
    if fname.find('.') == -1:
        fname += ".csv"
    f = open(fname, 'w')
    AddMessage(f'Saving {len(points)} points to "{fname}" ')
    f.write("Time,Temperature,Event\n")
    for p in points:
        f.write(f'{p[0] * 60.0},{p[1]},\n')  # What is meant to be encoded by label? is it stages?
        # f.write(f'{p[0] * 60.0},{p[1]},"{p}"\n')  # What is meant to be encoded by label? is it stages?
    f.close()


#############################
# save using a file dialog
# noinspection PyUnusedLocal
def bSaveAs(event):
    openFileDialog = wx.FileDialog(ui, "Save As", "", "",
                                   "CSV files (*.csv)|*.csv",
                                   wx.FD_SAVE)
    button_pressed = openFileDialog.ShowModal()
    if button_pressed == wx.ID_CANCEL:
        return
    filename = openFileDialog.GetFilename()
    if filename:
        filename = str(filename)
        if os.path.dirname(filename) == os.path.realpath(os.curdir):
            filename = os.path.basename(filename)
        ui.file_entry_box.SetValue(filename)
        bSave(None)


###############
# shutdown
# noinspection PyUnusedLocal
def bQuit(event):
    global pcontrol
    # kill off the meter reader child
    if not nodmm:
        os.kill(dmm.pid, signal.SIGTERM)
    if pcontrol:
        pcontrol.write("0%\r\n")
        pcontrol.setDTR(0)
    ctimer.Stop()
    ui.Close()


################
# setup the plot
# parameters
def SetupPlot(plot):  # dmmPlot, profile):
    global dmmPlot, LoadedProfile
    plot.axes.set_xlim(0.0, gMaxTime)
    plot.axes.set_ylim(0.0, gMaxTemp)
    plot.axes.set_ylabel("Temperature (" + u'\N{DEGREE SIGN}' + "C)")
    plot.axes.set_xlabel("Time (minutes)")
    dmmPlot = plot.axes.plot([], [], color='blue')[0]
    LoadedProfile = plot.axes.plot([], [], color='orange')[0]


###################################
# get the target temperature
def GetTarget() -> float:
    if ui.vTarget.GetValue() != 0:
        return ui.vTarget.GetValue()
    return ProfileTemperature()


###################################
# adjust the amount of power to the heat gun
def PowerControl():
    global CurrentTemperature, current_power
    global pcontrol

    target = GetTarget()
    elapsed = ElapsedTime() / 60.0
    dt = elapsed - PID_lastt
    # don't change the power level more than once every 2 seconds

    if dt < 2 / 60.0:
        return

    error = target - CurrentTemperature
    roc = RateOfChange()
    power = current_power
    # predict the temperature 30 seconds
    predict = error - (2 * roc)
    power = power + (predict / 60)

    if power > 100:
        power = 100
    elif power < 0:
        power = 0

    if ui.auto_power_chkbx.GetValue() is not True:
        power = ui.power_slider.GetValue()
    if int(power) != int(current_power):
        AddMessage("power => " + str(int(power)))
    if pcontrol is not None:
        spower = power
        if spower > 99:
            spower = 99
        pcontrol.setDTR(1)
        # pcontrol.write("%u%%\r\n" % int(spower))
        pcontrol.write(f"{int(spower)}%")
    current_power = power
    ui.power_slider.SetValue(int(current_power))


def PID_PowerControl():
    global CurrentTemperature, PID_integral, PID_previous_error, current_power
    global PID_lastt, pcontrol

    current = CurrentTemperature
    target = GetTarget()
    elapsed = ElapsedTime() / 60.0
    dt = elapsed - PID_lastt
    # don't change the power level more than once every 2 seconds

    if dt < 2 / 60.0:
        return

    error = target - CurrentTemperature
    PID_integral = PID_integral + (error * dt)
    derivative = (error - PID_previous_error) / dt
    output = (PID_Kp * error) + (PID_Ki * PID_integral) + (PID_Kd * derivative)
    #    AddMessage("dt=%f Kp_term=%f Ki_term=%f Kd_term=%f" % (dt,PID_Kp*error,PID_Ki*PID_integral,PID_Kd*derivative))
    PID_previous_error = error
    PID_lastt = elapsed

    # decay the integral component over 1 minute to 10%
    decay = math.exp(dt * math.log(0.1))
    PID_integral = PID_integral * decay

    # map output into power level.
    # testing shows that 50% means keep at current temp
    power = int(output + current_power)
    if power > 100:
        power = 100
    elif power < 0:
        power = 0

    if ui.auto_power_chkbx.GetValue():
        DebugMessage("current=%f target=%f PID Output %f power=%f" % (current, target, output, power))
    else:
        power = ui.power_slider.GetValue()
    if power != current_power:
        AddMessage("setting power to " + str(power))
    if pcontrol is not None:
        spower = power
        pcontrol.setDTR(1)
        pcontrol.write("%u%%\r\n" % spower)
    current_power = power
    ui.power_slider.SetValue(current_power)


####################
# called when we get a temp value
def GotTemperature(temp, temp2=None):
    global CurrentTemperature, MaxTemperature, TemperatureArray
    if len(TemperatureArray) >= gTempArraySize:
        del TemperatureArray[:1]
    if temp <= 0.0:
        return
    if temp2:
        temp = (temp + temp2) / 2
        # ui.tCurrentTemperature2.setText(f"{temp2:.1f}")  # FIXME not sure where this element is meant to live
    TemperatureArray.append(temp)
    CurrentTemperature = sum(TemperatureArray) / len(TemperatureArray)
    if CurrentTemperature > MaxTemperature:
        MaxTemperature = CurrentTemperature
    ui.current_temp.SetLabel(f"{CurrentTemperature:.1f}")
    ui.maximum_temp.SetLabel(f"{MaxTemperature:.1f}")
    ui.rate_of_change.SetLabel(("%.1f" + u'\N{DEGREE SIGN}' + "C/m") % RateOfChange())
    PowerControl()


#################################
# map the strange hex formatted
# DMM digits for a Victor 86B DMM
# to a normal digit
def MapDigit(d):
    digitMap = {
        0x03: '2',
        0x04: '2',
        0x05: '2',
        0x25: '9',
        0x26: '9',
        0x27: '9',
        0x2D: '5',
        0x2E: '5',
        0x2F: '5',
        0x41: '0',
        0x42: '0',
        0x43: '0',
        0x45: '8',
        0x46: '8',
        0x47: '8',
        0x4D: '6',
        0x4E: '6',
        0x4F: '6',
        0x60: '1',
        0x61: '1',
        0x62: '1',
        0xA4: '4',
        0xA5: '4',
        0xA6: '4',
        0xE0: '7',
        0xE1: '7',
        0xE2: '7',
        0xE5: '3',
        0xE6: '3',
        0xE7: '3'}

    ret = ""
    if d & 0x10:
        ret += "."
    if not digitMap[d & 0xEF]:
        AddMessage("Bad digit: %02x" % d)

    ret += digitMap[d & 0xEF]
    return ret


############################
# work out the rate of change
# of the temperature
def RateOfChange() -> float:
    points = dmmPlot.get_data()
    numpoints = len(points[0])
    if numpoints < 10:
        return 0
    x1 = 0
    y1 = 0
    x2 = points[0][-1]
    y2 = points[1][-1]
    for i in range(2, numpoints - 2):
        if x2 - points[0][-i] > 5.0 / 60:
            x1 = points[0][-i]
            y1 = points[1][-i]
            break
    if x1 == 0:
        return 0
    return (y2 - y1) / (x2 - x1)


def DeltaT(T, P, Tbase) -> float:
    r = 0.0085
    k = 0.0040
    return r * P - k * (T - Tbase)


############################
# simulate temperature profile
def SimulateTemperature():
    global sim_last_time, sim_base_temp, current_power
    global TempCells, NumCells
    if sim_last_time == 0:
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
    if elapsed < 0.5:
        return

    sim_last_time = t

    TempCells[0] += DeltaT(TempCells[0], current_power, sim_base_temp) * elapsed
    for i in range(1, NumCells):
        TempCells[i] = (TempCells[i - 1] + TempCells[i]) / 2

    GotTemperature(TempCells[NumCells - 1])


############################
# simulate temperature profile
def OLD_SimulateTemperature():
    global sim_last_time, sim_last_temp, sim_base_temp
    global PowerArray, PowerArraySize
    if sim_last_time == 0:
        sim_last_time = ElapsedTime()
        sim_last_temp = sim_base_temp
        GotTemperature(sim_last_temp)
        PowerArray = {}
        PowerArraySize = 50
        return
    t = ElapsedTime()
    ielapsed = int(t)
    elapsed = (t - sim_last_time)
    # the CS DMM gives a value every 0.5 seconds
    if elapsed < 0.5:
        return
    sim_last_time = t
    PowerArray[str(ielapsed)] = current_power
    if str(ielapsed - PowerArraySize) in PowerArray.keys():
        del PowerArray[str(ielapsed - PowerArraySize)]
    power = 0
    count = 0
    for i in range(0, PowerArraySize):
        if str(ielapsed - i) in PowerArray.keys():
            power += PowerArray[str(ielapsed - i)]
            count = count + 1
    power = power / count
    sim_last_temp += DeltaT(sim_last_temp, power, sim_base_temp) * elapsed
    DebugMessage(("sim_last_temp=%.2f current_power=%.2f sim_base_temp=%.2f elapsed=%.2f DeltaT=%.2f" % (
        sim_last_temp, current_power, sim_base_temp, elapsed, DeltaT(sim_last_temp, power, sim_base_temp))))
    GotTemperature(sim_last_temp)


############################
# check for input from the DMM
def CheckDMMInput():
    global CurrentTemperature, MaxTemperature
    if simulate_temp:
        SimulateTemperature()
        return
    if nodmm:
        return
    while select.select([dmm_file], [], [], 0)[0]:
        line = dmm_file.readline().strip()
        s = line.split()

        if len(s) != 15:
            AddMessage("Invalid DMM data: " + str(line))
            return
        if s[12] != "BF" \
                or s[13] != "6E" \
                or s[14] != "6C":
            AddMessage("DMM not in temperature mode: " + str(line))
            return

        # oh what a strange format the data is in ...
        d1 = int(s[11][0] + s[4][0], 16)
        d2 = int(s[10][0] + s[7][0], 16)
        d3 = int(s[8][0] + s[6][0], 16)
        d4 = int(s[1][0] + s[3][0], 16)
        d3 ^= 0x10
        try:
            temp = float(MapDigit(d1) + MapDigit(d2) + MapDigit(d3) + MapDigit(d4))
            GotTemperature(temp)

        except KeyError as ke:  # KeyError should be occuring in MapDigit()
            print(ke)
            AddMessage(f"Bad DMM digits {d1:02x} {d2:02x} {d3:02x} {d4:02x}")


############################
# check for input from the power controller
def PcontrolRead():
    global CurrentTemperature, MaxTemperature
    global pcontrol
    if pcontrol is None:
        return
    while select.select([pcontrol], [], [], 0)[0]:
        line = pcontrol.readline().strip()
        print(line)
        try:
            tarray = line.split()
            if tarray[0] == "T":
                ambient = float(tarray[1])
                temperature1 = float(tarray[2])
                temperature2 = float(tarray[3])
                GotTemperature(temperature1, temperature2)
                print(f"ambient={round(ambient, 1)} "
                      f"temperature1={round(temperature1, 1)} "
                      f"temperature2={round(temperature2, 1)}")
        except IndexError as ie:
            print(ie)
            pass


def Temp2Read():
    global CurrentTemperature, MaxTemperature
    global temp2
    if temp2 is None:
        return
    while select.select([temp2], [], [], 0)[0]:
        line = temp2.readline().strip()
        print(line)
        try:
            tarray = line.split()
            ambient = float(tarray[0])
            temperature1 = float(tarray[1])
            temperature2 = float(tarray[2])
            GotTemperature(temperature1, temperature2)
            print(f"ambient={round(ambient, 1)} "
                  f"temperature1={round(temperature1, 1)} "
                  f"temperature2={round(temperature2, 1)}")
        except IndexError as ie:
            print(ie)
            pass


############################
# called once a second
# noinspection PyUnusedLocal
def tick(event):
    global CurrentTemperature
    elapsed = ElapsedTime() / 60.0
    CheckDMMInput()
    Temp2Read()
    PcontrolRead()
    print(CurrentTemperature)
    if CurrentTemperature != 0:
        oldx, oldy = dmmPlot.get_data()
        newx = np.append(oldx, elapsed)
        newy = np.append(oldy, CurrentTemperature)
        dmmPlot.set_data(newx, newy)
    ui.elapsed_time.SetLabel(TimeString())
    ui.temperature_plot.draw()


#############################
# choose a reasonable default
# file name
def ChooseDefaultFileName():
    fname = time.strftime("%Y%m%d") + ".csv"
    i = 1
    while os.path.exists(fname):
        i += 1
        fname = time.strftime("%Y%m%d") + "-" + str(i) + ".csv"
    ui.file_entry_box.SetValue(fname)


############################
# open a serial port for
# power control
def PcontrolOpen(file):
    s = serial.Serial(file, 9600, parity='N', rtscts=False,
                      xonxoff=False, timeout=1.0)
    time.sleep(0.2)
    s.setDTR(1)
    return s


############################
# open a serial port for
# temp readings
def Temp2Open(file):
    s = serial.Serial(file, 9600, parity='N', rtscts=False,
                      xonxoff=False, timeout=1.0)
    return s


#############################
def usage():
    print(
        """
Usage: pyRoast.py [options]
Options:
  -h                   show this help
  --verbose	       verbose messages
  --simulate	       simulate temperature readings
  --profile PROFILE    preload a profile
  --pcontrol FILE      send PID power control to FILE
  --temp2 FILE         get 2nd temperature sources from FILE
  --nodmm	       don't try to read digital multimeter
  --smooth N	       smooth temperature over N values
"""
    )


class PyCoffee(wx.App):

    def OnInit(self):
        self.program_frame = PyCoffeeFrame(None, id=wx.ID_ANY, title="")
        self.SetTopWindow(self.program_frame)
        self.program_frame.Show()
        return True


############################################
# main program
# TODO work with Tridge about integrating second temperature read.
if __name__ == "__main__":
    import sys

    try:
        opts, args = getopt.getopt(sys.argv[1:], "h",
                                   ["help", "smooth=", "pcontrol=",
                                    "profile=", "simulate", "verbose",
                                    "speedup=", "maxtemp=", "maxtime=",
                                    "temp2=", "nodmm"])
    except getopt.GetoptError as err:
        print(str(err))
        usage()
        sys.exit(2)

    # TODO, if Roasting in the era of python >3.10, a switch-case statement would do well here.
    for o, a in opts:
        if o == ("-h", "--help"):
            usage()
            sys.exit(1)
        elif o == "--verbose":
            verbose = True
        elif o == "--simulate":
            simulate_temp = True
            nodmm = True
        elif o == "--speedup":
            time_speedup = int(a)
        elif o == "--mktemp":
            gMaxTemp = int(a)
        elif o == "--maxtime":
            gMaxTime = int(a)
        elif o == "--smooth":
            gTempArraySize = int(a)
        elif o == "--profile":
            profile_file = a
        elif o == "--pcontrol":
            pcontrol_dev = a
        elif o == "--temp2":
            temp2_dev = a
        elif o == "--nodmm":
            nodmm = True
        else:
            assert False, "unhandled option"

    PC = PyCoffee()
    ui = PC.program_frame

    # create plot of multimeter

    SetupPlot(ui.temperature_plot)

    # connect up the buttons
    ui.Bind(wx.EVT_BUTTON, bQuit, ui.quit_btn)
    ui.Bind(wx.EVT_BUTTON, bSave, ui.save_btn)
    ui.Bind(wx.EVT_BUTTON, bSaveAs, ui.save_as_btn)
    ui.Bind(wx.EVT_BUTTON, bReset, ui.reset_btn)
    ui.Bind(wx.EVT_BUTTON, bLoadProfile, ui.load_profile_btn)
    ui.Bind(wx.EVT_BUTTON, bFirstCrack, ui.first_crack_btn)
    ui.Bind(wx.EVT_BUTTON, bRollingFirstCrack, ui.rolling_first_crack_btn)
    ui.Bind(wx.EVT_BUTTON, bSecondCrack, ui.second_crack_btn)
    ui.Bind(wx.EVT_BUTTON, bRollingSecondCrack, ui.rolling_second_crack_btn)
    ui.Bind(wx.EVT_BUTTON, bUnload, ui.unload_btn)

    # get the current time
    StartTime = time.time()
    TemperatureArray = []
    CurrentTemperature = 0.0
    MaxTemperature = 0.0
    current_power = 0

    ui.power_slider.SetValue(current_power)
    ui.auto_power_chkbx.SetValue(True)

    # start the dmm child
    if not nodmm:
        dmm = subprocess.Popen(rmr, stdout=subprocess.PIPE)
        dmm_file = dmm.stdout

    if pcontrol_dev:
        AddMessage("opening power control " + str(pcontrol_dev))
        pcontrol = PcontrolOpen(pcontrol_dev)

    if temp2_dev:
        AddMessage("opening pauls temperature contraption " + str(temp2_dev))
        temp2 = Temp2Open(temp2_dev)

    # set a default file name
    ChooseDefaultFileName()

    if profile_file:
        LoadProfile(profile_file)

    AddMessage("Welcome to pyRoast " + gVersion)

    ctimer = wx.Timer(owner=ui, id=wx.ID_ANY)
    ui.Bind(wx.EVT_TIMER, tick, ctimer)
    ctimer.Start(milliseconds=int((1000 * gUpdateFrequency) / time_speedup))

    PC.MainLoop()
