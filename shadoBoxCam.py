# -*- coding: utf-8 -*-
"""
shadoBoxCam.py — Driver Python pour le Shad-o-Box 3K HS
Version SIMPLE et STABLE basée sur Snap()+Save() sans callback.
"""

import ctypes
import numpy as np
import threading
import time
import os
import tempfile
import tifffile

DEFAULT_DLL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "DalsaCamera_x64.dll"
)

FRAMERATE_MIN    = 0.1
FRAMERATE_MAX    = 10.0
EXPOSURE_MIN_MS  = 0.1
EXPOSURE_MAX_MS  = 9000.0
READOUT_MARGIN_S = 0.005

TEMP_TIFF = os.path.join(tempfile.gettempdir(), "shadobox_frame.tiff")
TRIGGER_SLICE_MS = 5000  # tranche pour boucle interruptible mode trigger (5s)

lock = threading.Lock()


class Camera:
    def __init__(self, dll_path=None):
        self._dll_path     = dll_path or DEFAULT_DLL_PATH
        self._dll          = None
        self._connected    = False
        self._server_idx   = -1   # -1 = auto-detect
        self._res_idx      = 0
        self._last_frame   = None
        self._acquiring    = False
        self._stop_acq     = False
        self._exposure_ms  = 100.0
        self._framerate    = 1.0
        self._trigger_mode = 0
        self.w = 2304
        self.h = 1300
        self.totalFrameSize = self.w * self.h
        self._load_dll()

    def _load_dll(self):
        if not os.path.exists(self._dll_path):
            raise FileNotFoundError(f"DLL introuvable : {self._dll_path}")
        self._dll = ctypes.CDLL(self._dll_path)
        self._setup_signatures()

    def _setup_signatures(self):
        d = self._dll
        d.InitializeCamera.argtypes   = [ctypes.c_int, ctypes.c_int]
        d.InitializeCamera.restype    = ctypes.c_int
        d.CleanupCamera.restype       = None
        d.ListCameras.restype         = ctypes.c_int
        d.GetImageSize.argtypes       = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        d.GetImageSize.restype        = ctypes.c_int
        d.CaptureImage.argtypes       = [ctypes.c_char_p]
        d.CaptureImage.restype        = ctypes.c_int
        d.CaptureImageTiff.argtypes   = [ctypes.c_char_p]
        d.CaptureImageTiff.restype    = ctypes.c_int
        d.CaptureImageTiffSlice.argtypes = [ctypes.c_char_p, ctypes.c_int]
        d.CaptureImageTiffSlice.restype  = ctypes.c_int
        d.AbortAcquisition.restype    = None
        d.SendSoftwareTrigger.argtypes = []
        d.SendSoftwareTrigger.restype  = ctypes.c_int
        d.SetFeatureFloat.argtypes    = [ctypes.c_char_p, ctypes.c_double]
        d.SetFeatureFloat.restype     = ctypes.c_int
        d.GetFeatureFloat.argtypes    = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_double)]
        d.GetFeatureFloat.restype     = ctypes.c_int
        d.SetFeatureInt.argtypes      = [ctypes.c_char_p, ctypes.c_longlong]
        d.SetFeatureInt.restype       = ctypes.c_int
        d.GetFeatureInt.argtypes      = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_longlong)]
        d.GetFeatureInt.restype       = ctypes.c_int
        d.SetFeatureString.argtypes   = [ctypes.c_char_p, ctypes.c_char_p]
        d.SetFeatureString.restype    = ctypes.c_int
        d.GetFeatureString.argtypes   = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        d.GetFeatureString.restype    = ctypes.c_int
        d.IsFeatureAvailable.argtypes = [ctypes.c_char_p]
        d.IsFeatureAvailable.restype  = ctypes.c_int
        d.ListAllFeatures.argtypes    = [ctypes.c_char_p, ctypes.c_int]
        d.ListAllFeatures.restype     = ctypes.c_int
        d.SetExposureTime.argtypes    = [ctypes.c_double]
        d.SetExposureTime.restype     = ctypes.c_int
        d.GetExposureTime.argtypes    = [ctypes.POINTER(ctypes.c_double)]
        d.GetExposureTime.restype     = ctypes.c_int
        d.SetGain.argtypes            = [ctypes.c_double]
        d.SetGain.restype             = ctypes.c_int
        d.GetGain.argtypes            = [ctypes.POINTER(ctypes.c_double)]
        d.GetGain.restype             = ctypes.c_int
        d.SetTriggerMode.argtypes     = [ctypes.c_int]
        d.SetTriggerMode.restype      = ctypes.c_int
        d.SetFrameRate.argtypes       = [ctypes.c_double]
        d.SetFrameRate.restype        = ctypes.c_int
        d.GetFrameRate.argtypes       = [ctypes.POINTER(ctypes.c_double)]
        d.GetFrameRate.restype        = ctypes.c_int
        d.SetROI.argtypes             = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        d.SetROI.restype              = ctypes.c_int
        d.SetBinning.argtypes         = [ctypes.c_int, ctypes.c_int]
        d.SetBinning.restype          = ctypes.c_int
        d.SetTimeout.argtypes         = [ctypes.c_int]
        d.SetTimeout.restype          = None
        d.GetTimeout.restype          = ctypes.c_int

    def _setF(self, name, value): return self._dll.SetFeatureFloat(name.encode(), float(value)) == 1
    def _getF(self, name):
        v = ctypes.c_double(0)
        ok = self._dll.GetFeatureFloat(name.encode(), ctypes.byref(v))
        return v.value if ok else None
    def _setI(self, name, value): return self._dll.SetFeatureInt(name.encode(), int(value)) == 1
    def _getI(self, name):
        v = ctypes.c_longlong(0)
        ok = self._dll.GetFeatureInt(name.encode(), ctypes.byref(v))
        return v.value if ok else None
    def _setS(self, name, value): return self._dll.SetFeatureString(name.encode(), value.encode()) == 1
    def _getS(self, name):
        buf = ctypes.create_string_buffer(256)
        ok = self._dll.GetFeatureString(name.encode(), buf, len(buf))
        return buf.value.decode() if ok else None

    def _optimal_framerate(self, ms):
        s = float(ms) / 1000.0
        fps = 1.0 / (s * 1.1 + READOUT_MARGIN_S)
        return max(FRAMERATE_MIN, min(FRAMERATE_MAX, round(fps, 3)))

    def getAvailableCameras(self):
        return self._dll.ListCameras()

    def _findShadoBoxServer(self):
        """
        Trouve automatiquement l'index serveur du Shad-o-Box
        en cherchant 'ShadoBox' ou 'Shado' dans le nom du serveur.
        Utilise GetServerName via la DLL.
        """
        import ctypes as ct

        # Ajouter GetServerName si pas déjà fait
        try:
            self._dll.GetServerName.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
            self._dll.GetServerName.restype  = ctypes.c_int
        except Exception:
            pass

        # Compter les serveurs
        try:
            sc = self._dll.GetCameraCount()
        except Exception:
            sc = 20

        # Chercher via GetServerName dans la DLL
        for srv in range(30):
            try:
                buf = ctypes.create_string_buffer(256)
                ok = self._dll.GetServerName(srv, buf, len(buf))
                if ok:
                    name = buf.value.decode().lower()
                    if "shado" in name:
                        print(f"Shad-o-Box trouvé sur serveur {srv} : {buf.value.decode()}")
                        return srv
            except Exception:
                break
        return -1

    def OpenCamerabySerial(self, serial=None):
        # Auto-détection du serveur Shad-o-Box si index non fixé
        if self._server_idx == -1:
            self._server_idx = self._findShadoBoxServer()
            if self._server_idx == -1:
                raise RuntimeError("Shad-o-Box non trouvé. Vérifiez le câble GigE.")

        if not self._dll.InitializeCamera(self._server_idx, self._res_idx):
            raise RuntimeError("Impossible de connecter le Shad-o-Box.")
        self._connected = True
        # Délai plus long pour laisser le pilote GigE se stabiliser
        try:
            time.sleep(1.0)
        except KeyboardInterrupt:
            pass

        w, h = ctypes.c_int(0), ctypes.c_int(0)
        self._dll.GetImageSize(ctypes.byref(w), ctypes.byref(h))
        self.w, self.h = w.value, h.value
        self.totalFrameSize = self.w * self.h

        try:
            v = ctypes.c_double(0)
            if self._dll.GetExposureTime(ctypes.byref(v)):
                self._exposure_ms = v.value / 1000.0
            if self._dll.GetFrameRate(ctypes.byref(v)):
                self._framerate = v.value
        except Exception as e:
            print(f"Lecture paramètres initiale : {e}")

        try:
            t = self.GetTemperature()
        except Exception:
            t = 25.0

        print(f"Shad-o-Box connecté  {self.w}×{self.h} px  "
              f"T={t:.1f}°C  Expo={self._exposure_ms:.1f}ms  FPS={self._framerate:.2f}")

    def getSerialNumber(self):
        try:
            if self._dll.IsFeatureAvailable(b"DeviceSerialNumber"):
                buf = ctypes.create_string_buffer(256)
                if self._dll.GetFeatureString(b"DeviceSerialNumber", buf, len(buf)) and buf.value:
                    return buf.value.decode()
        except Exception:
            pass
        return "unknown"

    def disconnect(self):
        self._stop_acq = True
        try: self._dll.AbortAcquisition()
        except Exception: pass
        try: self._dll.CleanupCamera()
        except Exception as e: print(f"disconnect : {e}")
        self._connected = False

    def SetExposure(self, ms):
        ms = max(EXPOSURE_MIN_MS, min(EXPOSURE_MAX_MS, float(ms)))
        fps = self._optimal_framerate(ms)
        self._dll.SetFrameRate(fps)
        self._framerate = fps
        self._dll.SetExposureTime(float(ms * 1000.0))
        self._exposure_ms = ms
        print(f"Exposition={ms:.1f}ms  →  FrameRate={fps:.3f}fps")

    def GetExposure(self):
        v = ctypes.c_double(0)
        if self._dll.GetExposureTime(ctypes.byref(v)): self._exposure_ms = v.value / 1000.0
        return self._exposure_ms

    def setFrameRate(self, fps):
        fps = max(FRAMERATE_MIN, min(FRAMERATE_MAX, float(fps)))
        self._dll.SetFrameRate(fps)
        self._framerate = fps

    def getFrameRate(self):
        v = ctypes.c_double(0)
        if self._dll.GetFrameRate(ctypes.byref(v)): self._framerate = v.value
        return self._framerate

    _PARAM_MAP = {
        "PicamParameter_ExposureTime": "exp",
        "PicamParameter_TriggerResponse": "trig",
        "PicamParameter_TriggerDetermination": "noop",
        "PicamParameter_TriggerSource": "noop",
        "PicamParameter_SensorTemperatureSetPoint": "noop",
        "PicamParameter_SensorTemperatureReading": "temp",
        "PicamParameter_SensorTemperatureStatus": "tstat",
        "PicamParameter_CleanCycleCount": "noop",
        "PicamParameter_CleanCycleHeight": "noop",
        "PicamParameter_CleanUntilTrigger": "noop",
        "PicamParameter_CleanBeforeExposure": "noop",
        "PicamParameter_AdcAnalogGain": "noop",
        "PicamParameter_AdcSpeed": "noop",
        "PicamParameter_AdcQuality": "noop",
        "PicamParameter_AdcEMGain": "noop",
    }

    def setParameter(self, name, value):
        typ = self._PARAM_MAP.get(name)
        if typ is None: self._setAutoType(name, value); return
        if typ == "noop": return
        if typ == "exp": self.SetExposure(float(value))
        elif typ == "trig":
            ext = 0 if int(value) == 1 else 1
            self._trigger_mode = ext
            self._dll.SetTriggerMode(ext)
            time.sleep(0.5)

    def getParameter(self, name):
        typ = self._PARAM_MAP.get(name)
        if typ is None: return self._getAutoType(name)
        if typ == "noop":  return 0
        if typ == "exp":   return self.GetExposure()
        if typ == "temp":  return self.GetTemperature()
        if typ == "tstat": return self.GetTemperatureStatus()
        if typ == "trig":  return 2 if self._trigger_mode == 1 else 1
        return None

    def _setAutoType(self, name, value):
        if isinstance(value, str):     self._setS(name, value)
        elif isinstance(value, float): self._setF(name, value)
        else:                          self._setI(name, int(value))

    def _getAutoType(self, name):
        v = self._getI(name)
        if v is not None: return v
        v = self._getF(name)
        if v is not None: return v
        return self._getS(name)

    def setROI(self, x0, w, xbin, y0, h, ybin, store=0):
        self._dll.SetROI(int(x0), int(w), int(y0), int(h))
        if xbin > 1 or ybin > 1: self._dll.SetBinning(int(xbin), int(ybin))
        self.w = int(w / xbin)
        self.h = int(h / ybin)
        self.totalFrameSize = self.w * self.h

    def Acquisition(self, N=1, timeout=120000):
        """
        FreeRunning : CaptureImageTiff bloquant (rapide)
        ExtTrigger  : boucle CaptureImageTiffSlice(500ms) interruptible
        """
        if not self._connected:
            print("Acquisition : caméra non connectée")
            return None
        if self._acquiring:
            print("Acquisition déjà en cours, ignorée")
            return None
        self._stop_acq = False
        self._acquiring = True
        self._last_frame = None
        t = time.time()

        with lock:
            try:
                if self._trigger_mode == 0:
                    # FreeRunning
                    ok = self._dll.CaptureImageTiff(TEMP_TIFF.encode())
                    if ok == 1:
                        self._last_frame = tifffile.imread(TEMP_TIFF).astype(np.uint16)
                else:
                    # ExtTrigger : timeout fixe de 5 minutes
                    # (indépendant du FrameRate qui peut être erroné en mode trigger)
                    wait_ms = 300000  # 5 minutes
                    self._dll.SetTimeout(wait_ms)
                    print(f"Attente trigger externe (timeout={wait_ms//1000}s)...")

                    import threading as _th
                    result = [0]

                    def _snap():
                        result[0] = self._dll.CaptureImageTiff(TEMP_TIFF.encode())

                    t_snap = _th.Thread(target=_snap, daemon=True)
                    t_snap.start()

                    # Attendre en vérifiant _stop_acq toutes les 200ms
                    while t_snap.is_alive():
                        if self._stop_acq:
                            self._dll.AbortAcquisition()
                            t_snap.join(5.0)  # attendre jusqu'à 5s
                            print("Acquisition interrompue")
                            break
                        time.sleep(0.2)

                    # Si le thread est encore vivant après abort, on attend quand même
                    if t_snap.is_alive():
                        t_snap.join(3.0)

                    if result[0] == 1 and not self._stop_acq:
                        self._last_frame = tifffile.imread(TEMP_TIFF).astype(np.uint16)
                        print("Trigger reçu !")
            except Exception as e:
                print(f"Acquisition : {e}")
            finally:
                self._acquiring = False

        elapsed = time.time() - t
        print(f"Durée acquisition : {elapsed:.3f}s  "
              f"(expo={self._exposure_ms:.1f}ms  trig={'EXT' if self._trigger_mode else 'FREE'})")
        return t

    def IsAcquisitionRunning(self): return self._acquiring and not self._stop_acq

    def StopAcquisition(self):
        self._stop_acq = True
        self._acquiring = False
        try:
            if self._trigger_mode == 1:
                # Soft trigger pour débloquer immédiatement le Wait()
                self._dll.SendSoftwareTrigger()
            self._dll.AbortAcquisition()
        except Exception:
            pass

    def GetAcquiredData(self):
        if self._last_frame is None:
            return np.zeros((self.h, self.w), dtype=np.uint16)
        return self._last_frame

    def GetTemperature(self):
        t = self._getF("DeviceTemperature")
        return t if t is not None else 25.0

    def SetTemperature(self, t): pass
    def GetTemperatureStatus(self): return 2

    def setTimeout(self, ms): self._dll.SetTimeout(int(ms))
    def getTimeout(self): return self._dll.GetTimeout()

    def listAllFeatures(self):
        buf = ctypes.create_string_buffer(65536)
        self._dll.ListAllFeatures(buf, len(buf))
        return [f for f in buf.value.decode().split("\n") if f]

    def setDigitalGain(self, gain): self._dll.SetGain(float(gain))
    def getDigitalGain(self):
        v = ctypes.c_double(0)
        self._dll.GetGain(ctypes.byref(v))
        return v.value

    def saveTiff(self, filepath):
        return self._dll.CaptureImageTiff(filepath.encode()) == 1

    def getFrameRateForExposure(self, ms): return self._optimal_framerate(ms)


if __name__ == "__main__":
    cam = Camera()
    cam.OpenCamerabySerial()
    cam.SetExposure(100)
    cam.Acquisition()
    img = cam.GetAcquiredData()
    print(f"Image: {img.shape}  min={img.min()}  max={img.max()}  mean={img.mean():.1f}")
    cam.disconnect()
