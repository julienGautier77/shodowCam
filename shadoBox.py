# -*- coding: utf-8 -*-
"""
shadoBox.py
===========
Widget PyQt6 de contrôle du Teledyne Shad-o-Box 3K HS (5GigE).
Calqué sur princeton.py / ROPPER.

@author: juliengautier (adapté LOA)
"""

import __init__
__version__ = __init__.__version__
__author__  = __init__.__author__
version     = __version__

from PyQt6.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout, QWidget,
                              QPushButton, QToolButton, QLayout, QMenu,
                              QDockWidget, QDoubleSpinBox, QGridLayout,
                              QComboBox, QSlider, QLabel, QSpinBox,
                              QInputDialog, QSizePolicy, QCheckBox,
                              QProgressBar, QMessageBox)
from PyQt6 import QtCore
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
import sys, time
import signal
import numpy as np
import pathlib
import os
import pyqtgraph as pg

# Empêcher Python d'intercepter SIGINT (évite KeyboardInterrupt aléatoire)
signal.signal(signal.SIGINT, signal.SIG_DFL)

try:
    import shadoBoxCam
except Exception:
    print('shadoBoxCam introuvable — caméra non disponible')
    shadoBoxCam = None

import qdarkstyle
from visu import SEE


# ══════════════════════════════════════════════════════════════════════════════
class SHADOWIDGET(QWidget):

    signalData       = QtCore.pyqtSignal(object)
    updateBar_signal = QtCore.pyqtSignal(object)

    def __init__(self, cam=None, confFile='confCCD.ini', **kwds):
        super().__init__()

        self.progressWin = ProgressScreen(parent=self)
        self.progressWin.setWindowFlags(
            Qt.WindowType.SplashScreen | Qt.WindowType.WindowStaysOnTopHint)
        self.progressWin.show()

        p    = pathlib.Path(__file__)
        sepa = os.sep
        self.version = version
        self.icon    = str(p.parent) + sepa + 'icons' + sepa

        self.nbcam       = cam if cam is not None else 'shadoBox'
        self.isConnected = False
        self.kwds        = kwds
        self.camIsRunnig = False
        self.nbShot      = 1
        self.itrig       = 0   # 0=FreeRunning, 1=ExtTrigger

        if 'confpath' in kwds:
            self.confpath = kwds['confpath']
        else:
            self.confpath = str(p.parent / confFile)
        self.kwds['confpath'] = self.confpath
        self.conf = QtCore.QSettings(self.confpath,
                                     QtCore.QSettings.Format.IniFormat)

        self.light    = kwds.get('affLight', False)
        self.aff      = kwds.get('aff', 'right')
        self.separate = kwds.get('separate', False)

        self.setWindowIcon(QIcon(self.icon + 'LOA.png'))
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt6'))

        def _icon(name):
            return pathlib.PurePosixPath(pathlib.Path(self.icon + name))
        self.iconPlay = _icon('Play.png')
        self.iconSnap = _icon('Snap.png')
        self.iconStop = _icon('Stop.png')

        self.ccdName = self.conf.value(self.nbcam + '/nameCDD', 'Shad-o-Box 3K HS')
        self.serial  = self.conf.value(self.nbcam + '/serial', '0')

        self.updateBar_signal.emit(['Connexion caméra …', 25])
        self.initCam()
        self.updateBar_signal.emit(['Chargement interface …', 75])
        self.setup()
        self.actionButton()
        self.camIsRunnig = False
        self.updateBar_signal.emit(['end', 100])
        self.progressWin.close()

    # ── Initialisation caméra ─────────────────────────────────────────────────

    def initCam(self):
        if shadoBoxCam is None:
            return
        self.cam = shadoBoxCam.Camera()
        self.cam.getAvailableCameras()
        try:
            self.cam.OpenCamerabySerial(serial=self.serial)
            self.isConnected = True
        except Exception as e:
            print(f'Connexion impossible : {e}')
            self.isConnected = False

        self.serial = self.cam.getSerialNumber()
        if self.serial == 'SLTest:Demo':
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle('Attention')
            msg.setText('Caméra de démonstration connectée')
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.setWindowIcon(QIcon(self.icon + 'LOA.png'))
            msg.exec()

    # ── Interface ─────────────────────────────────────────────────────────────

    def setup(self):
        bsz   = 30
        vbox1 = QVBoxLayout()
        hbox1 = QHBoxLayout()

        # ── Boutons Run / Snap / Stop ──────────────────────────────────────────
        def _tbtn(icon_path):
            b = QToolButton(self)
            b.setFixedSize(bsz, bsz)
            b.setStyleSheet(
                f"QToolButton:!pressed{{border-image:url({icon_path});"
                f"background-color:transparent;}}"
                f"QToolButton:pressed{{border-image:url({icon_path});"
                f"background-color:gray;}}")
            return b

        self.runButton  = _tbtn(self.iconPlay)
        self.stopButton = _tbtn(self.iconStop)
        self.stopButton.setEnabled(False)
        self.stopButton.setStyleSheet(
            f"QToolButton:!pressed{{border-image:url({self.iconStop});"
            f"background-color:gray;border-color:gray;}}"
            f"QToolButton:pressed{{border-image:url({self.iconStop});"
            f"background-color:gray;border-color:gray;}}")

        self.snapButton = QToolButton(self)
        self.snapButton.setFixedSize(bsz, bsz)
        self.snapButton.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu()
        menu.addAction('Nombre de snapshots', self.nbShotAction)
        self.snapButton.setMenu(menu)
        self.snapButton.setStyleSheet(
            f"QToolButton:!pressed{{border-image:url({self.iconSnap});"
            f"background-color:transparent;}}"
            f"QToolButton:pressed{{border-image:url({self.iconSnap});"
            f"background-color:gray;}}")

        hbox1.addWidget(self.runButton)
        hbox1.addWidget(self.snapButton)
        hbox1.addWidget(self.stopButton)
        hbox1.setSizeConstraint(QLayout.SizeConstraint.SetMaximumSize)
        hbox1.setContentsMargins(0, 0, 0, 0)
        hbox1.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # ── Trigger ────────────────────────────────────────────────────────────
        self.trigg = QComboBox()
        self.trigg.setMaximumWidth(90)
        self.trigg.addItem('OFF')
        self.trigg.addItem('ON')
        self.trigg.setStyleSheet('font:bold 10pt;color:white')
        labelTrig = QLabel('Trig')
        labelTrig.setMaximumWidth(50)
        hbox2 = QHBoxLayout()
        hbox2.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        hbox2.setContentsMargins(0, 20, 10, 10)
        hbox2.addWidget(labelTrig)
        hbox2.addWidget(self.trigg)
        wTrig = QWidget(self); wTrig.setLayout(hbox2)
        self.dockTrig = QDockWidget(self)
        self.dockTrig.setWidget(wTrig)
        self.dockTrig.setTitleBarWidget(QWidget())

        # ── Exposition ─────────────────────────────────────────────────────────
        self.labelExp = QLabel('Exposition (ms)')
        self.labelExp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hSliderShutter = QSlider(Qt.Orientation.Horizontal)
        self.hSliderShutter.setMaximumWidth(60)
        self.shutterBox = QSpinBox()
        self.shutterBox.setMaximum(100000)
        self.hSliderShutter.setMaximum(100000)
        hboxSh = QHBoxLayout()
        hboxSh.addWidget(self.hSliderShutter)
        hboxSh.addWidget(self.shutterBox)
        vboxSh = QVBoxLayout()
        vboxSh.addWidget(self.labelExp)
        vboxSh.addLayout(hboxSh)
        vboxSh.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        vboxSh.setContentsMargins(0, 0, 10, 0)
        wSh = QWidget(self); wSh.setLayout(vboxSh)
        self.dockShutter = QDockWidget(self)
        self.dockShutter.setWidget(wSh)
        self.dockShutter.setTitleBarWidget(QWidget())

        # ── DigitalGain (1X ou 2X) ────────────────────────────────────────────
        labelGain = QLabel('Digital Gain')
        labelGain.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gainCombo = QComboBox()
        self.gainCombo.addItem('1X')
        self.gainCombo.addItem('2X')
        self.gainCombo.setMaximumWidth(80)
        vboxGain = QVBoxLayout()
        vboxGain.addWidget(labelGain)
        vboxGain.addWidget(self.gainCombo)
        vboxGain.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        wGain = QWidget(self); wGain.setLayout(vboxGain)
        self.dockGain = QDockWidget(self)
        self.dockGain.setWidget(wGain)
        self.dockGain.setTitleBarWidget(QWidget())

        # ── FrameRate ──────────────────────────────────────────────────────────
        labelFR = QLabel('Frame Rate (fps)')
        labelFR.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frateBox = QDoubleSpinBox()
        self.frateBox.setMinimum(0.1)
        self.frateBox.setMaximum(10.0)
        self.frateBox.setSingleStep(0.5)
        self.frateBox.setDecimals(1)
        self.frateBox.setMaximumWidth(80)
        vboxFR = QVBoxLayout()
        vboxFR.addWidget(labelFR)
        vboxFR.addWidget(self.frateBox)
        vboxFR.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        wFR = QWidget(self); wFR.setLayout(vboxFR)
        self.dockFR = QDockWidget(self)
        self.dockFR.setWidget(wFR)
        self.dockFR.setTitleBarWidget(QWidget())

        # ── Température ────────────────────────────────────────────────────────
        self.tempBox = QLabel('?')
        self.tempBox.setStyleSheet('font:bold 10pt;color:green')
        self.tempButton = QToolButton(self)
        self.tempButton.setFixedSize(bsz + 10, bsz)
        self.tempButton.setText('Temp')
        hbox1.addWidget(self.tempButton)
        hbox1.addWidget(self.tempBox)

        # ── Cam Settings ───────────────────────────────────────────────────────
        self.settingButton = QToolButton(self)
        self.settingButton.setFixedSize(bsz + 30, bsz)
        self.settingButton.setText('Cam Set.')
        hbox1.addWidget(self.settingButton)

        vbox1.addLayout(hbox1)
        vbox1.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        vbox1.setContentsMargins(0, 20, 10, 10)

        self.widgetControl = QWidget(self)
        self.widgetControl.setLayout(vbox1)
        self.dockControl = QDockWidget(self)
        self.dockControl.setWidget(self.widgetControl)
        self.dockControl.setTitleBarWidget(QWidget())

        # ── Visualisation ──────────────────────────────────────────────────────
        hMainLayout = QHBoxLayout()
        if self.light:
            from visu import SEELIGHT
            self.visualisation = SEELIGHT(parent=self, name=self.nbcam, **self.kwds)
        else:
            self.visualisation = SEE(parent=self, name=self.nbcam, **self.kwds)

        docks = [self.dockControl, self.dockTrig, self.dockShutter,
                 self.dockGain, self.dockFR]
        area = (Qt.DockWidgetArea.LeftDockWidgetArea if self.aff == 'left'
                else Qt.DockWidgetArea.RightDockWidgetArea)
        for d in docks:
            if self.separate:
                self.visualisation.addDockWidget(area, d)
            else:
                self.visualisation.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, d)

        hMainLayout.addWidget(self.visualisation)
        self.setLayout(hMainLayout)
        self.setContentsMargins(0, 0, 0, 0)

        # ── Init valeurs ───────────────────────────────────────────────────────
        if self.isConnected:
            self.sh = int(self.conf.value(self.nbcam + '/shutter', 100))
            self.shutterBox.setValue(self.sh)
            self.hSliderShutter.setValue(self.sh)

            fr = self.cam.getFrameRate()
            self.frateBox.setValue(float(fr))

            g = self.cam.getDigitalGain()
            self.gainCombo.setCurrentIndex(1 if g >= 2.0 else 0)

            self.dimx = self.cam.w
            self.dimy = self.cam.h
            self.cam.setROI(0, self.dimx, 1, 0, self.dimy, 1, 0)
            self.cam.SetExposure(self.sh)

            self.threadTemp    = ThreadTemperature(cam=self.cam, parent=self)
            self.threadRunAcq  = ThreadRunAcq(self)
            self.threadOneAcq  = ThreadOneAcq(self)
            self.threadTemp.TEMP.connect(self.update_temp)
            self.threadRunAcq.newDataRun.connect(self.Display)
            self.threadOneAcq.newDataRun.connect(self.Display)
            # Délai non bloquant pour Qt
            QtCore.QThread.msleep(500)
            self.threadTemp.start()

            self.settingWidget = SETTINGWIDGET(
                cam=self.cam, visualisation=self.visualisation,
                conf=self.conf, nbcam=self.nbcam)
        else:
            self.settingWidget = None

        self.setWindowTitle(
            f"Shad-o-Box 3K HS  {self.ccdName}  "
            f"s/n:{self.serial}  v.{self.version}  "
            f"Visu v.{self.visualisation.version}")

    # ── Température ───────────────────────────────────────────────────────────

    def update_temp(self, temp=None, stat=None):
        if temp is None:
            temp = 0
        if stat == 2:
            self.tempBox.setStyleSheet('font:bold 10pt;color:green')
        else:
            self.tempBox.setStyleSheet('font:bold 10pt;color:red')
        self.tempBox.setText(f'{temp:.1f} °C')

    # ── Boutons ───────────────────────────────────────────────────────────────

    def actionButton(self):
        self.runButton.clicked.connect(self.acquireMultiImage)
        self.snapButton.clicked.connect(self.acquireOneImage)
        self.stopButton.clicked.connect(self.stopAcq)
        self.shutterBox.editingFinished.connect(self.shutter)
        self.hSliderShutter.sliderReleased.connect(self.mSliderShutter)
        self.gainCombo.currentIndexChanged.connect(self.setGain)
        self.frateBox.editingFinished.connect(self.setFrameRate)
        self.trigg.currentIndexChanged.connect(self.Trigger)
        self.tempButton.clicked.connect(self._showTemp)
        if self.settingWidget:
            self.settingButton.clicked.connect(
                lambda: self.open_widget(self.settingWidget))

    # ── Exposition ────────────────────────────────────────────────────────────

    def shutter(self):
        self.sh = self.shutterBox.value()
        self.hSliderShutter.setValue(self.sh)
        self.cam.SetExposure(self.sh)
        # Mettre à jour le framerate affiché (SetExposure l'ajuste auto)
        self.frateBox.setValue(self.cam.getFrameRate())
        self.conf.setValue(self.nbcam + '/shutter', float(self.sh))
        self.conf.sync()

    def mSliderShutter(self):
        self.sh = self.hSliderShutter.value()
        self.shutterBox.setValue(self.sh)
        self.cam.SetExposure(self.sh)
        self.frateBox.setValue(self.cam.getFrameRate())
        self.conf.setValue(self.nbcam + '/shutter', float(self.sh))

    # ── Gain ──────────────────────────────────────────────────────────────────

    def setGain(self):
        g = 2.0 if self.gainCombo.currentIndex() == 1 else 1.0
        self.cam.setDigitalGain(g)

    # ── Frame Rate ────────────────────────────────────────────────────────────

    def setFrameRate(self):
        fr = self.frateBox.value()
        self.cam.setFrameRate(fr)

    # ── Trigger ───────────────────────────────────────────────────────────────

    def Trigger(self):
        """
        Identique à ROPPER.Trigger :
        - OFF → FreeRunning, timeout normal (30s)
        - ON  → ExtTrigger, timeout 5 min
                Run arme et réarme le trigger en boucle (comme ROPPER)
                Snap arme une seule fois
        """
        self.itrig = self.trigg.currentIndex()

        # Arrêter l'acquisition en cours proprement
        self.stopAcq()
        # Attendre la fin effective des threads
        try:
            self.threadRunAcq.wait(2000)
        except Exception:
            pass
        try:
            self.threadOneAcq.wait(2000)
        except Exception:
            pass
        # Attendre que _acquiring repasse à False
        for _ in range(50):
            if not self.cam._acquiring:
                break
            time.sleep(0.1)
        time.sleep(0.5)

        if self.itrig == 0:
            # FreeRunning
            self.cam.setTimeout(30000)
            self.cam.setParameter('PicamParameter_TriggerResponse', int(1))
            print('Trigger OFF (FreeRunning)')
        else:
            # ExtTrigger — timeout 5 min pour attendre le trigger
            self.cam.setTimeout(300000)
            self.cam.setParameter('PicamParameter_TriggerResponse', int(2))
            print('Trigger ON (ExtTrigger) — Run ou Snap pour armer')

    # ── Acquisition ───────────────────────────────────────────────────────────

    def _setButtonsAcq(self, acquiring):
        """Grise/dégrise les boutons pendant l'acquisition."""
        idle = not acquiring

        # ── Boutons Run/Snap/Stop avec style explicite ─────────────────────────
        if acquiring:
            # Acquisition en cours : Run et Snap grisés, Stop actif
            self.runButton.setEnabled(False)
            self.runButton.setStyleSheet(
                f"QToolButton:!pressed{{border-image:url({self.iconPlay});"
                f"background-color:gray;border-color:gray;}}"
                f"QToolButton:pressed{{border-image:url({self.iconPlay});"
                f"background-color:gray;border-color:gray;}}")
            self.snapButton.setEnabled(False)
            self.snapButton.setStyleSheet(
                f"QToolButton:!pressed{{border-image:url({self.iconSnap});"
                f"background-color:gray;border-color:gray;}}"
                f"QToolButton:pressed{{border-image:url({self.iconSnap});"
                f"background-color:gray;border-color:gray;}}")
            self.stopButton.setEnabled(True)
            self.stopButton.setStyleSheet(
                f"QToolButton:!pressed{{border-image:url({self.iconStop});"
                f"background-color:transparent;border-color:gray;}}"
                f"QToolButton:pressed{{border-image:url({self.iconStop});"
                f"background-color:gray;border-color:gray;}}")
        else:
            # Idle : Run et Snap actifs, Stop grisé
            self.runButton.setEnabled(True)
            self.runButton.setStyleSheet(
                f"QToolButton:!pressed{{border-image:url({self.iconPlay});"
                f"background-color:transparent;}}"
                f"QToolButton:pressed{{border-image:url({self.iconPlay});"
                f"background-color:gray;}}")
            self.snapButton.setEnabled(True)
            self.snapButton.setStyleSheet(
                f"QToolButton:!pressed{{border-image:url({self.iconSnap});"
                f"background-color:transparent;}}"
                f"QToolButton:pressed{{border-image:url({self.iconSnap});"
                f"background-color:gray;}}")
            self.stopButton.setEnabled(False)
            self.stopButton.setStyleSheet(
                f"QToolButton:!pressed{{border-image:url({self.iconStop});"
                f"background-color:gray;border-color:gray;}}"
                f"QToolButton:pressed{{border-image:url({self.iconStop});"
                f"background-color:gray;border-color:gray;}}")

        # ── Autres contrôles ───────────────────────────────────────────────────
        self.trigg.setEnabled(idle)
        self.hSliderShutter.setEnabled(idle)
        self.shutterBox.setEnabled(idle)
        self.gainCombo.setEnabled(idle)
        self.frateBox.setEnabled(idle)
        if self.settingWidget:
            for c in self.settingWidget.findChildren(QPushButton):
                c.setEnabled(idle)
            for c in self.settingWidget.findChildren(QComboBox):
                c.setEnabled(idle)

        QtCore.QCoreApplication.processEvents()

    def acquireOneImage(self):
        """Snap : N shots (ou 1 shot en mode trigger = arme une fois)."""
        try:
            self.threadTemp.stopThreadTemp()
        except Exception:
            pass
        self._setButtonsAcq(True)
        self.threadOneAcq.newRun()
        self.threadOneAcq.start()
        self.camIsRunnig = True

    def acquireMultiImage(self):
        """
        Run continu.
        En mode FreeRunning : acquisition continue.
        En mode ExtTrigger  : arme et réarme en boucle (comme ROPPER).
        """
        try:
            self.threadTemp.stopThreadTemp()
        except Exception:
            pass
        self._setButtonsAcq(True)
        self.threadRunAcq.newRun()
        self.threadRunAcq.start()
        self.camIsRunnig = True

    def stopAcq(self):
        """Arrêt propre — abort si bloqué en attente de trigger."""
        # Aborter une éventuelle acquisition bloquée
        if self.isConnected:
            try:
                self.cam._dll.AbortAcquisition()
            except Exception:
                pass
        if self.isConnected:
            self.cam.StopAcquisition()
        try:
            self.threadRunAcq.stopThreadRunAcq()
        except Exception:
            pass
        try:
            self.threadOneAcq.stopThreadRunAcq()
        except Exception:
            pass
        # Attendre que les threads se terminent vraiment
        try:
            self.threadRunAcq.wait(2000)
        except Exception:
            pass
        try:
            self.threadOneAcq.wait(2000)
        except Exception:
            pass
        print('Acquisition arrêtée')
        # Redémarrer thread température
        try:
            self.threadTemp.newRun()
            self.threadTemp.start()
        except Exception:
            pass
        self._setButtonsAcq(False)
        self.camIsRunnig = False

    def Display(self, data):
        self.signalData.emit(data)

    # ── Utilitaires ───────────────────────────────────────────────────────────

    def nbShotAction(self):
        n, ok = QInputDialog.getInt(self, 'Nombre de snapshots',
                                    'Entrer le nombre de snapshots :',
                                    value=self.nbShot, min=1)
        if ok:
            self.nbShot = max(1, int(n))

    def open_widget(self, fene):
        if not fene.isWinOpen:
            fene.show()
            fene.isWinOpen = True
        else:
            fene.raise_()
            fene.showNormal()

    def _showTemp(self):
        temp = self.cam.GetTemperature()
        QMessageBox.information(self, 'Température',
                                f'Température boîtier : {temp:.1f} °C')

    def closeEvent(self, event):
        try:
            self.threadTemp.stopThreadTemp()
        except Exception:
            pass
        if self.isConnected:
            try:
                self.cam._dll.AbortAcquisition()
            except Exception:
                pass
        time.sleep(0.2)
        if self.isConnected:
            self.cam.disconnect()
        time.sleep(0.1)
        if self.settingWidget and self.settingWidget.isWinOpen:
            self.settingWidget.close()
        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
# Threads
# ══════════════════════════════════════════════════════════════════════════════

class ThreadRunAcq(QtCore.QThread):
    """
    Acquisition continue — identique à ROPPER.ThreadRunAcq.
    En mode ExtTrigger : Snap() bloque jusqu'au trigger, puis réarme.
    """
    newDataRun = QtCore.pyqtSignal(object)

    def __init__(self, parent):
        super().__init__()
        self.stopRunAcq = False
        self.parent = parent
        self.cam    = parent.cam

    def newRun(self):
        self.stopRunAcq = False

    def run(self):
        print('-----> Démarrage acquisition continue')
        while True:
            if self.stopRunAcq:
                break
            if not self.cam.IsAcquisitionRunning():
                self.cam.Acquisition(N=1, timeout=120000)
                # Vérifier stop APRES acquisition (important en mode trigger)
                if self.stopRunAcq:
                    break
                print('-----> Acquisition')
                try:
                    data = self.cam.GetAcquiredData()
                    data = np.array(data, dtype=np.double)
                    self.newDataRun.emit(data)
                except Exception:
                    pass
            else:
                time.sleep(0.01)

    def stopThreadRunAcq(self):
        self.stopRunAcq = True
        self.cam.StopAcquisition()


class ThreadOneAcq(QtCore.QThread):
    """Acquisition N shots."""
    newDataRun = QtCore.pyqtSignal(object)

    def __init__(self, parent):
        super().__init__()
        self.stopRunAcq = False
        self.parent = parent
        self.cam    = parent.cam

    def newRun(self):
        self.stopRunAcq = False

    def run(self):
        print(f'-----> Démarrage {self.parent.nbShot} acquisition(s)')
        for _ in range(self.parent.nbShot):
            if self.stopRunAcq:
                break
            if not self.cam.IsAcquisitionRunning():
                self.cam.Acquisition(N=1, timeout=120000)
                print('-----> Acquisition')
                try:
                    data = self.cam.GetAcquiredData()
                    data = np.array(data, dtype=np.double)
                    self.newDataRun.emit(data)
                except Exception:
                    pass
            else:
                time.sleep(0.01)
        self.parent.stopAcq()

    def stopThreadRunAcq(self):
        self.stopRunAcq = True
        self.cam.StopAcquisition()


class ThreadTemperature(QtCore.QThread):
    TEMP = QtCore.pyqtSignal(float, int)

    def __init__(self, parent=None, cam=None):
        super().__init__()
        self.cam      = cam
        self.stopTemp = False

    def run(self):
        while True:
            try:
                temp = self.cam.GetTemperature()
                stat = int(self.cam.GetTemperatureStatus())
                self.TEMP.emit(temp, stat)
            except Exception:
                pass
            time.sleep(2)
            if self.stopTemp:
                break

    def stopThreadTemp(self):
        self.stopTemp = True

    def newRun(self):
        self.stopTemp = False


# ══════════════════════════════════════════════════════════════════════════════
# Widget paramètres (ROI)
# ══════════════════════════════════════════════════════════════════════════════

class SETTINGWIDGET(QWidget):

    def __init__(self, cam=None, visualisation=None, conf=None,
                 nbcam=None, parent=None):
        super().__init__(parent)
        self.cam           = cam
        self.visualisation = visualisation
        self.conf          = conf
        self.nbcam         = nbcam
        self.isWinOpen     = False
        self.roi1Is        = False
        self.dimx          = cam.w
        self.dimy          = cam.h
        self.setWindowTitle('Shad-o-Box — Paramètres')
        self.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt6'))
        self.setWindowIcon(QIcon('./icons/LOA.png'))
        self.setup()
        self.actionButton()

    def setup(self):
        self.vbox = QVBoxLayout()
        hbuttonROI = QVBoxLayout()
        self.setROIButton      = QPushButton('Set ROI')
        self.setROIFullButton  = QPushButton('Full Frame')
        self.setROIMouseButton = QPushButton('Mouse')
        hbuttonROI.addWidget(self.setROIButton)
        hbuttonROI.addWidget(self.setROIFullButton)
        hbuttonROI.addWidget(self.setROIMouseButton)

        grid = QGridLayout()

        def _spin(mn, mx, val):
            s = QSpinBox(); s.setMinimum(mn); s.setMaximum(mx); s.setValue(val)
            return s

        x0   = int(self.conf.value(self.nbcam + '/x0',   0))
        y0   = int(self.conf.value(self.nbcam + '/y0',   0))
        wroi = int(self.conf.value(self.nbcam + '/wroi', self.dimx))
        hroi = int(self.conf.value(self.nbcam + '/hroi', self.dimy))

        self.ROIX = _spin(0, self.dimx, x0)
        self.ROIY = _spin(0, self.dimy, y0)
        self.ROIW = _spin(1, self.dimx, wroi)
        self.ROIH = _spin(1, self.dimy, hroi)
        self.BINX = _spin(1, 4, 1)
        self.BINY = _spin(1, 4, 1)

        for row, (lbl, widget) in enumerate([
            ('ROI Xo', self.ROIX), ('ROI Yo', self.ROIY),
            ('ROI Dx', self.ROIW), ('ROI Dy', self.ROIH),
            ('Bin X',  self.BINX), ('Bin Y',  self.BINY)]):
            grid.addWidget(QLabel(lbl), row, 0)
            grid.addWidget(widget,      row, 1)

        hboxROI = QHBoxLayout()
        hboxROI.addLayout(hbuttonROI)
        hboxROI.addLayout(grid)
        self.vbox.addLayout(hboxROI)

        self.r1   = 100
        self.roi1 = pg.RectROI([self.dimx/2 - self.r1, self.dimy/2 - self.r1],
                               [2*self.r1, 2*self.r1], pen='r', movable=True)
        self.setLayout(self.vbox)

    def actionButton(self):
        self.setROIButton.clicked.connect(self.roiSet)
        self.setROIFullButton.clicked.connect(self.roiFull)
        self.setROIMouseButton.clicked.connect(self.mouseROI)
        self.roi1.sigRegionChangeFinished.connect(self.mousFinished)

    def mouseROI(self):
        self.visualisation.p1.addItem(self.roi1)
        self.roi1Is = True

    def mousFinished(self):
        pos  = self.roi1.pos()
        size = self.roi1.size()
        self.ROIX.setValue(int(pos.x()))
        self.ROIY.setValue(int(pos.y()))
        self.ROIW.setValue(int(size.x()))
        self.ROIH.setValue(int(size.y()))

    def roiSet(self):
        x0 = max(0, self.ROIX.value())
        y0 = max(0, self.ROIY.value())
        w  = min(self.ROIW.value(), self.dimx)
        h  = min(self.ROIH.value(), self.dimy)
        bx = self.BINX.value()
        by = self.BINY.value()
        if self.roi1Is:
            self.visualisation.p1.removeItem(self.roi1)
            self.roi1Is = False
        self.cam.setROI(x0, w, bx, y0, h, by, 1)
        self.conf.setValue(self.nbcam + '/x0',   x0)
        self.conf.setValue(self.nbcam + '/y0',   y0)
        self.conf.setValue(self.nbcam + '/wroi', w)
        self.conf.setValue(self.nbcam + '/hroi', h)
        self.conf.sync()

    def roiFull(self):
        self.cam.setROI(0, self.dimx, 1, 0, self.dimy, 1, 1)
        print('Full frame')
        if self.roi1Is:
            self.visualisation.p1.removeItem(self.roi1)
            self.roi1Is = False

    def closeEvent(self, event):
        self.isWinOpen = False
        if self.roi1Is:
            self.visualisation.p1.removeItem(self.roi1)
            self.roi1Is = False
        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
# Écran de chargement
# ══════════════════════════════════════════════════════════════════════════════

class ProgressScreen(QWidget):

    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        p    = pathlib.Path(__file__)
        sepa = os.sep
        icon = str(p.parent) + sepa + 'icons' + sepa
        self.setWindowIcon(QIcon(icon + 'LOA.png'))
        self.setWindowTitle('Chargement …')
        self.setGeometry(600, 300, 300, 100)
        layout = QVBoxLayout()
        lbl2   = QLabel("Laboratoire d'Optique Appliquée")
        lbl2.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lbl2.setStyleSheet('font:bold 20pt;color:white')
        lbl1   = QLabel('Shad-o-Box 3K HS  v' + str(__version__))
        lbl1.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.action       = QLabel('Initialisation …')
        self.progress_bar = QProgressBar()
        layout.addWidget(lbl2)
        layout.addWidget(lbl1)
        layout.addWidget(self.action)
        layout.addWidget(self.progress_bar)
        self.setLayout(layout)
        if self.parent is not None:
            self.parent.updateBar_signal.connect(self.setLabel)

    def setLabel(self, labels):
        self.action.setText(str(labels[0]))
        self.progress_bar.setValue(int(labels[1]))
        QtCore.QCoreApplication.processEvents()


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    import warnings
    warnings.filterwarnings('ignore')
    appli = QApplication(sys.argv)
    appli.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyqt6'))
    e = SHADOWIDGET(cam='shadoBox')
    e.show()
    appli.exec()
