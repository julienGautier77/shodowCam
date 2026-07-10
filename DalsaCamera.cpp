// DalsaCamera.cpp
// Wrapper C++ pour Python (ctypes) - Teledyne Shad-o-Box 3K HS
// Version SIMPLE et STABLE :
//   - SapBuffer simple (1 buffer), pas de SapBufferWithTrash
//   - PAS de callback (cause de BSOD)
//   - Snap() + Wait() bloquant
//
// Compilation : build.bat

#pragma warning(disable: 4127 4995)
#include "stdio.h"
#include "windows.h"
#include "sapclassbasic.h"
#include <string>
#include <cstring>
#pragma warning(default: 4995)

// ── Objets globaux ────────────────────────────────────────────────────────────
static SapAcqDevice*      g_pAcqDevice = nullptr;
static SapBuffer*         g_pBuffer    = nullptr;
static SapAcqDeviceToBuf* g_pXfer      = nullptr;
static int                g_timeoutMs  = 30000;

// ── Declarations export ───────────────────────────────────────────────────────
extern "C" {
    __declspec(dllexport) int  InitializeCamera   (int serverIndex, int resourceIndex);
    __declspec(dllexport) void CleanupCamera       ();
    __declspec(dllexport) int  ListCameras         ();
    __declspec(dllexport) int  GetCameraCount      ();
    __declspec(dllexport) int  GetImageSize        (int* width, int* height);
    __declspec(dllexport) int  GetServerName       (int serverIndex, char* outBuf, int bufLen);

    __declspec(dllexport) int  CaptureImage        (const char* filename);
    __declspec(dllexport) int  CaptureImageTiff    (const char* filename);
    // Timeout court interruptible : 1=OK, -1=timeout partiel, 0=erreur
    __declspec(dllexport) int  CaptureImageTiffSlice(const char* filename, int sliceMs);
    __declspec(dllexport) void AbortAcquisition    ();
    __declspec(dllexport) int  SendSoftwareTrigger ();

    __declspec(dllexport) int  SetFeatureFloat     (const char* name, double value);
    __declspec(dllexport) int  GetFeatureFloat     (const char* name, double* value);
    __declspec(dllexport) int  SetFeatureInt       (const char* name, long long value);
    __declspec(dllexport) int  GetFeatureInt       (const char* name, long long* value);
    __declspec(dllexport) int  SetFeatureString    (const char* name, const char* value);
    __declspec(dllexport) int  GetFeatureString    (const char* name, char* outBuf, int bufLen);
    __declspec(dllexport) int  IsFeatureAvailable  (const char* name);
    __declspec(dllexport) int  ListAllFeatures     (char* outBuf, int bufLen);

    __declspec(dllexport) int  SetExposureTime     (double microseconds);
    __declspec(dllexport) int  GetExposureTime     (double* microseconds);
    __declspec(dllexport) int  SetGain             (double gain);
    __declspec(dllexport) int  GetGain             (double* gain);
    __declspec(dllexport) int  SetTriggerMode      (int external);
    __declspec(dllexport) int  SetFrameRate        (double fps);
    __declspec(dllexport) int  GetFrameRate        (double* fps);
    __declspec(dllexport) int  SetROI              (int offX, int w, int offY, int h);
    __declspec(dllexport) int  SetBinning          (int binX, int binY);
    __declspec(dllexport) void SetTimeout          (int ms);
    __declspec(dllexport) int  GetTimeout          ();
}

// ── Helpers ───────────────────────────────────────────────────────────────────
static bool _chk() { return g_pAcqDevice != nullptr; }
static bool _setD(const char* n, double v)       { return _chk() && g_pAcqDevice->SetFeatureValue(n,v)==TRUE; }
static bool _getD(const char* n, double& v)      { return _chk() && g_pAcqDevice->GetFeatureValue(n,&v)==TRUE; }
static bool _setI(const char* n, INT64 v)        { return _chk() && g_pAcqDevice->SetFeatureValue(n,v)==TRUE; }
static bool _getI(const char* n, INT64& v)       { return _chk() && g_pAcqDevice->GetFeatureValue(n,&v)==TRUE; }
static bool _setS(const char* n, const char* v)  { return _chk() && g_pAcqDevice->SetFeatureValue(n,v)==TRUE; }
static bool _getS(const char* n, char* b, int l) { return _chk() && g_pAcqDevice->GetFeatureValue(n,b,l)==TRUE; }
static bool _avail(const char* n) {
    if (!_chk()) return false;
    BOOL a=FALSE; g_pAcqDevice->IsFeatureAvailable(n,&a); return a==TRUE;
}

static void _destroyXferBuf() {
    if (g_pXfer)   { g_pXfer->Destroy();   delete g_pXfer;   g_pXfer=nullptr; }
    if (g_pBuffer) { g_pBuffer->Destroy(); delete g_pBuffer; g_pBuffer=nullptr; }
}

static bool _createXferBuf() {
    // SapBuffer SIMPLE - PAS de SapBufferWithTrash, PAS de callback
    g_pBuffer = new SapBuffer(1, g_pAcqDevice);
    if (!g_pBuffer->Create()) { printf("Echec Buffer\n"); return false; }
    g_pXfer = new SapAcqDeviceToBuf(g_pAcqDevice, g_pBuffer);
    if (!g_pXfer->Create()) { printf("Echec Xfer\n"); return false; }
    return true;
}

// ── Connexion ─────────────────────────────────────────────────────────────────
int InitializeCamera(int serverIndex, int resourceIndex)
{
    try {
        // Ne pas appeler CleanupCamera ici - les objets globaux sont
        // déjà nullptr au premier appel, et un re-init doit passer par
        // un Cleanup explicite depuis Python d'abord
        if (g_pAcqDevice || g_pBuffer || g_pXfer) {
            CleanupCamera();
            Sleep(500);
        }
        // Délai pour laisser le pilote GigE se stabiliser
        Sleep(1500);
        int sc = SapManager::GetServerCount();
        if (serverIndex < 0 || serverIndex >= sc) {
            printf("Serveur invalide : %d\n", serverIndex); return 0;
        }
        int rc = SapManager::GetResourceCount(serverIndex, SapManager::ResourceAcqDevice);
        if (rc == 0) {
            printf("Aucune AcqDevice sur serveur %d\n", serverIndex); return 0;
        }
        if (resourceIndex < 0 || resourceIndex >= rc) {
            printf("Ressource invalide : %d\n", resourceIndex); return 0;
        }
        g_pAcqDevice = new SapAcqDevice(SapLocation(serverIndex, resourceIndex), FALSE);
        if (!g_pAcqDevice->Create()) {
            printf("Echec AcqDevice\n");
            delete g_pAcqDevice; g_pAcqDevice=nullptr; return 0;
        }
        // Délai pour laisser le pilote initialiser complètement la connexion
        Sleep(500);
        if (!_createXferBuf()) return 0;

        char model[64]="?";
        if (_avail("DeviceModelName")) _getS("DeviceModelName", model, sizeof(model));
        printf("Camera: %s (Srv:%d Res:%d)\n", model, serverIndex, resourceIndex);
        return 1;
    }
    catch (...) { printf("Exception InitializeCamera\n"); return 0; }
}

void CleanupCamera()
{
    try {
        _destroyXferBuf();
        if (g_pAcqDevice) { g_pAcqDevice->Destroy(); delete g_pAcqDevice; g_pAcqDevice=nullptr; }
    } catch (...) {}
}

// ── Listing ───────────────────────────────────────────────────────────────────
int ListCameras()
{
    try {
        int sc = SapManager::GetServerCount();
        printf("Serveurs: %d\n", sc);
        for (int i=0; i<sc; i++) {
            char name[256]; SapManager::GetServerName(i, name, sizeof(name));
            int n = SapManager::GetResourceCount(i, SapManager::ResourceAcqDevice);
            printf("  [%d] %s (%d AcqDevice)\n", i, name, n);
            for (int j=0; j<n; j++) {
                char rn[256];
                SapManager::GetResourceName(i, SapManager::ResourceAcqDevice, j, rn, sizeof(rn));
                printf("      [%d] %s\n", j, rn);
            }
        }
        return sc;
    } catch (...) { return 0; }
}

int GetCameraCount()
{
    try {
        int t=0, sc=SapManager::GetServerCount();
        for (int i=0; i<sc; i++)
            t += SapManager::GetResourceCount(i, SapManager::ResourceAcqDevice);
        return t;
    } catch (...) { return 0; }
}

int GetImageSize(int* w, int* h)
{
    if (!g_pBuffer) return 0;
    *w = g_pBuffer->GetWidth();
    *h = g_pBuffer->GetHeight();
    return 1;
}

int GetServerName(int serverIndex, char* outBuf, int bufLen)
{
    try {
        return SapManager::GetServerName(serverIndex, outBuf, bufLen) ? 1 : 0;
    } catch (...) { return 0; }
}

// ── Acquisition ───────────────────────────────────────────────────────────────

int CaptureImage(const char* filename)
{
    if (!g_pXfer || !g_pBuffer) return 0;
    try {
        if (!g_pXfer->Snap()) return 0;
        if (!g_pXfer->Wait(g_timeoutMs)) return 0;
        return g_pBuffer->Save(filename, "-format bmp") ? 1 : 0;
    } catch (...) { return 0; }
}

int CaptureImageTiff(const char* filename)
{
    if (!g_pXfer || !g_pBuffer) return 0;
    try {
        if (!g_pXfer->Snap()) return 0;
        if (!g_pXfer->Wait(g_timeoutMs)) return 0;
        return g_pBuffer->Save(filename, "-format tiff") ? 1 : 0;
    } catch (...) { return 0; }
}

// Snap avec timeout court — interruptible depuis Python
// Retourne 1=OK, -1=timeout partiel (utile pour mode trigger), 0=erreur
int CaptureImageTiffSlice(const char* filename, int sliceMs)
{
    if (!g_pXfer || !g_pBuffer) return 0;
    try {
        if (!g_pXfer->Snap()) return 0;
        if (!g_pXfer->Wait(sliceMs)) {
            // Pas de trigger reçu : freeze proprement (PAS Abort)
            g_pXfer->Freeze();
            g_pXfer->Wait(3000);
            // Délai supplémentaire pour libérer la ressource
            Sleep(100);
            return -1;
        }
        return g_pBuffer->Save(filename, "-format tiff") ? 1 : 0;
    } catch (...) { return 0; }
}

void AbortAcquisition()
{
    if (!g_pXfer) return;
    try {
        // Freeze proprement, attendre plus longtemps
        g_pXfer->Freeze();
        // Wait long : laisser le pilote terminer son transfert en cours
        g_pXfer->Wait(3000);
        // NE PAS appeler Abort() - cause des BSOD avec le pilote Sapera
        printf("Acquisition stoppée proprement\n");
    } catch (...) {}
}

// Envoie un software trigger pour débloquer un Wait() en mode ExtTrigger
// Permet au Stop de répondre immédiatement sans attendre un vrai trigger
int SendSoftwareTrigger()
{
    if (!_chk()) return 0;
    try {
        // SoftwareTrigger est une commande Execute sur le Shad-o-Box
        INT64 val = 1;
        return g_pAcqDevice->SetFeatureValue("SoftwareTrigger", val) ? 1 : 0;
    } catch (...) { return 0; }
}

// ── GenICam ───────────────────────────────────────────────────────────────────
int SetFeatureFloat  (const char* n, double v)      { return _setD(n,v)?1:0; }
int GetFeatureFloat  (const char* n, double* v)     { return _getD(n,*v)?1:0; }
int SetFeatureString (const char* n, const char* v) { return _setS(n,v)?1:0; }
int GetFeatureString (const char* n, char* b, int l){ return _getS(n,b,l)?1:0; }
int IsFeatureAvailable(const char* n)               { return _avail(n)?1:0; }
int SetFeatureInt(const char* n, long long v)       { return _setI(n,(INT64)v)?1:0; }
int GetFeatureInt(const char* n, long long* v) {
    INT64 t=0; bool ok=_getI(n,t); *v=(long long)t; return ok?1:0;
}
int ListAllFeatures(char* outBuf, int bufLen)
{
    if (!_chk()) return 0;
    int count=0;
    g_pAcqDevice->GetFeatureCount(&count);
    std::string result;
    for (int i=0; i<count; i++) {
        char name[64]="";
        if (g_pAcqDevice->GetFeatureNameByIndex(i, name, sizeof(name)))
            result += std::string(name)+"\n";
    }
    strncpy_s(outBuf, bufLen, result.c_str(), _TRUNCATE);
    return count;
}

// ── Raccourcis ────────────────────────────────────────────────────────────────
int SetExposureTime(double us) {
    if (_setI("SoftwareTrigIntTime",(INT64)us)) return 1;
    return _setD("ExposureTime",us)?1:0;
}
int GetExposureTime(double* us) {
    INT64 v=0;
    if (_getI("SoftwareTrigIntTime",v)){*us=(double)v;return 1;}
    return _getD("ExposureTime",*us)?1:0;
}

int SetGain(double g) {
    if (_avail("DigitalGain")) {
        const char* val = (g >= 2.0) ? "TWOX" : "ONEX";
        return _setS("DigitalGain", val) ? 1 : 0;
    }
    if (_avail("Gain")) return _setD("Gain",g)?1:0;
    return 0;
}
int GetGain(double* g) {
    if (_avail("DigitalGain")) {
        char val[64]="";
        if (_getS("DigitalGain", val, sizeof(val))) {
            *g = (strncmp(val,"TWO",3)==0) ? 2.0 : 1.0;
            return 1;
        }
    }
    if (_avail("Gain")) return _getD("Gain",*g)?1:0;
    return 0;
}

int SetTriggerMode(int ext)
{
    // Aborter toute acquisition en cours
    AbortAcquisition();
    Sleep(300);

    if (ext)
        return _setS("SynchronizationMode","ExtTrigger") ? 1 : 0;
    return _setS("SynchronizationMode","FreeRunning") ? 1 : 0;
}

int SetFrameRate(double fps) {
    if (_setD("FrameRate",fps)) return 1;
    return _setD("AcquisitionFrameRate",fps)?1:0;
}
int GetFrameRate(double* fps) {
    if (_getD("FrameRate",*fps)) return 1;
    return _getD("AcquisitionFrameRate",*fps)?1:0;
}

int SetROI(int offX, int w, int offY, int h) {
    if (!_chk()) return 0;
    if (_avail("ROIStartH")) {
        _setI("ROIStartH",offX); _setI("ROIStopH",offX+w-1);
        _setI("ROIStartV",offY); _setI("ROIStopV",offY+h-1);
    } else {
        _setI("OffsetX",0); _setI("OffsetY",0);
        _setI("Width",w);   _setI("Height",h);
        _setI("OffsetX",offX); _setI("OffsetY",offY);
    }
    _destroyXferBuf();
    return _createXferBuf() ? 1 : 0;
}

int SetBinning(int bx, int by) {
    if (!_chk()) return 0;
    _setI("BinningHorizontal",bx);
    _setI("BinningVertical",  by);
    _destroyXferBuf();
    return _createXferBuf() ? 1 : 0;
}

void SetTimeout(int ms) {
    g_timeoutMs = (ms > 0) ? ms : 30000;
    printf("Timeout : %d ms\n", g_timeoutMs);
}
int GetTimeout() { return g_timeoutMs; }
