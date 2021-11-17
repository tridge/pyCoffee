import math

import wx
from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np


class PyCoffeeFrame(wx.Frame):
    def __init__(self, *args, **kwds):
        kwds["style"] = kwds.get("style", 0) | wx.DEFAULT_FRAME_STYLE
        wx.Frame.__init__(self, *args, **kwds)

        self._set_properties()
        self._element_setup()
        self._do_layout()

        self.SetSize((865, 550))

    def _set_properties(self):
        self.SetTitle("PyCoffee - The Ferg edit")

    def _element_setup(self):
        self.figure = Figure((8.5, 3))
        self.canvas = FigureCanvas(self, wx.ID_ANY, self.figure)
        self.temperature_plot = LiveCoffeeGraph(self.canvas)

        self.coffee_img = wx.StaticBitmap(self, wx.ID_ANY, wx.Bitmap("./cslogo.png", wx.BITMAP_TYPE_ANY))
        self.temp_readout = wx.TextCtrl(self, id=wx.ID_ANY, value='', size=(220, 220), style=wx.VSCROLL | wx.TE_MULTILINE | wx.EXPAND)

        self.temperature_label = wx.StaticText(self, wx.ID_ANY, "Temperature:", style=wx.ALIGN_LEFT)
        self.max_temperature_label = wx.StaticText(self, wx.ID_ANY, "Max temperature:", style=wx.ALIGN_LEFT)
        self.Rate_of_change_label = wx.StaticText(self, wx.ID_ANY, "Rate of Change:", style=wx.ALIGN_LEFT)
        self.elapsed_time_label = wx.StaticText(self, wx.ID_ANY, "Elapsed time:", style=wx.ALIGN_LEFT)
        self.current_temp = wx.StaticText(self, wx.ID_ANY, "212.4", style=wx.ALIGN_RIGHT)
        self.maximum_temp = wx.StaticText(self, wx.ID_ANY, "250.4", style=wx.ALIGN_RIGHT)
        self.rate_of_change = wx.StaticText(self, wx.ID_ANY, ".04C/min", style=wx.ALIGN_RIGHT)
        self.elapsed_time = wx.StaticText(self, wx.ID_ANY, "00:00", style=wx.ALIGN_RIGHT)

        self.auto_power_chkbx = wx.CheckBox(self, id=wx.ID_ANY, label="Auto Power")
        self.power_slider = wx.Slider(self, wx.ID_ANY, value=67, minValue=0, maxValue=100, pos=wx.DefaultPosition, size=(250, -1), style=wx.SL_AUTOTICKS | wx.SL_HORIZONTAL | wx.SL_LABELS)

        self.first_crack_btn = wx.Button(self, wx.ID_ANY, label=" First \nCrack", size=wx.Size(90, 50))
        self.rolling_first_crack_btn = wx.Button(self, wx.ID_ANY, label="  Rolling \nFirst Crack", size=wx.Size(90, 50))
        self.second_crack_btn = wx.Button(self, wx.ID_ANY, label="Second \n  Crack", size=wx.Size(90, 50))
        self.rolling_second_crack_btn = wx.Button(self, wx.ID_ANY, label="     Rolling \nSecond Crack", size=wx.Size(90, 50))
        self.unload_btn = wx.Button(self, wx.ID_ANY, label="Unload", size=wx.Size(90, 50))

        self.file_name_label = wx.StaticText(self, wx.ID_ANY, "File Name:")
        self.file_entry_box = wx.TextCtrl(self, wx.ID_ANY, "20091203.csv", size=(200, 28))
        self.vTarget_label = wx.StaticText(self, wx.ID_ANY, "Target:")
        self.vTarget = wx.SpinCtrlDouble(self, wx.ID_ANY, "0.0", size=(150, 28), min=0, max=250, inc=0.5)

        self.reset_btn = wx.Button(self, wx.ID_ANY, label="Reset", size=wx.Size(90, 50))
        self.save_btn = wx.Button(self, wx.ID_ANY, label="Save", size=wx.Size(90, 50))
        self.save_as_btn = wx.Button(self, wx.ID_ANY, label="Save As", size=wx.Size(90, 50))
        self.load_profile_btn = wx.Button(self, wx.ID_ANY, label="Load Profile", size=wx.Size(90, 50))
        self.quit_btn = wx.Button(self, wx.ID_ANY, label="Quit", size=wx.Size(90, 50))

    def _do_layout(self):
        whole_win = wx.FlexGridSizer(rows=2, cols=1, hgap=0, vgap=0)
        graph_panel = wx.FlexGridSizer(rows=1, cols=1, hgap=0, vgap=0)
        options_panel = wx.FlexGridSizer(rows=1, cols=2, hgap=5, vgap=0)
        lower_left_panel = wx.FlexGridSizer(rows=5, cols=1, hgap=0, vgap=0)
        lower_right_panel = wx.FlexGridSizer(rows=1, cols=2, hgap=0, vgap=0)
        temp_panel = wx.FlexGridSizer(rows=2, cols=4, hgap=20, vgap=5)
        power_panel = wx.FlexGridSizer(rows=1, cols=2, hgap=0, vgap=0)
        stage_panel = wx.FlexGridSizer(rows=1, cols=5, hgap=0, vgap=0)
        save_panel = wx.FlexGridSizer(rows=1, cols=4, hgap=0, vgap=0)
        save_btn_panel = wx.FlexGridSizer(rows=1, cols=5, hgap=0, vgap=0)

        temp_panel.Add(self.temperature_label, proportion=1, flag=wx.EXPAND)
        temp_panel.Add(self.current_temp, proportion=1, flag=wx.EXPAND)
        temp_panel.Add(self.Rate_of_change_label, proportion=1, flag=wx.EXPAND)
        temp_panel.Add(self.rate_of_change, proportion=1, flag=wx.EXPAND)
        temp_panel.Add(self.max_temperature_label, proportion=1, flag=wx.EXPAND)
        temp_panel.Add(self.maximum_temp, proportion=1, flag=wx.EXPAND)
        temp_panel.Add(self.elapsed_time_label, proportion=1, flag=wx.EXPAND)
        temp_panel.Add(self.elapsed_time, proportion=1, flag=wx.EXPAND)

        graph_panel.Add(self.canvas)

        power_panel.Add(self.auto_power_chkbx, proportion=1, flag=wx.EXPAND, border=3)
        power_panel.Add(self.power_slider)

        stage_panel.Add(self.first_crack_btn)
        stage_panel.Add(self.rolling_first_crack_btn)
        stage_panel.Add(self.second_crack_btn)
        stage_panel.Add(self.rolling_second_crack_btn)
        stage_panel.Add(self.unload_btn)

        save_panel.Add(self.file_name_label, flag=wx.TOP | wx.BOTTOM, border=5)
        save_panel.Add(self.file_entry_box)
        save_panel.Add(self.vTarget_label, flag=wx.TOP | wx.BOTTOM, border=5)
        save_panel.Add(self.vTarget)


        save_btn_panel.Add(self.reset_btn)
        save_btn_panel.Add(self.save_btn)
        save_btn_panel.Add(self.save_as_btn)
        save_btn_panel.Add(self.load_profile_btn)
        save_btn_panel.Add(self.quit_btn)

        lower_right_panel.Add(self.coffee_img, flag=wx.EXPAND)
        lower_right_panel.Add(self.temp_readout, proportion=1, flag=wx.EXPAND)

        lower_left_panel.Add(temp_panel)
        lower_left_panel.Add(power_panel)
        lower_left_panel.Add(stage_panel)
        lower_left_panel.Add(save_panel)
        lower_left_panel.Add(save_btn_panel)

        options_panel.Add(lower_left_panel)
        options_panel.Add(lower_right_panel)

        whole_win.Add(graph_panel)
        whole_win.Add(options_panel)

        self.SetSizer(whole_win)

class LiveCoffeeGraph():
    def __init__(self, parent):
        self.axes = parent.figure.add_subplot(111)
        self.axes.autoscale_view('tight')
        parent.figure.subplots_adjust(bottom=0.19)
        self.canvas = parent
        # self.test_draw()

    def plot(self, elapsed, CurrentTemperature, label='', color='red'):
        self.axes.plot(elapsed, CurrentTemperature, label=label, color=color)

    def test_draw(self):
        t = list(np.arange(0, 30, 0.1))
        s = np.sin(t)*100+150
        self.axes.plot(t, s)

    def draw(self):
        self.canvas.draw_idle()
