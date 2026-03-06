const { app, BrowserWindow } = require('electron')
const path = require('path')
const { spawn } = require('child_process')

let pythonProcess = null

function getFFmpegPath() {
    if (app.isPackaged) {
        return path.join(process.resourcesPath, 'bin', 'ffmpeg.exe')
    } else {
        return path.join(__dirname, 'resources', 'bin', 'ffmpeg.exe')
    }
}

function getPythonScriptPath() {
    if (app.isPackaged) {
        return path.join(process.resourcesPath, 'main.py')
    } else {
        return path.join(__dirname, 'main.py')
    }
}

function startPythonDetector() {
    const ffmpegPath = getFFmpegPath()
    const scriptPath = getPythonScriptPath()

    console.log('FFmpeg path:', ffmpegPath)
    console.log('Python script:', scriptPath)

    pythonProcess = spawn('python', [scriptPath, '--ffmpeg', ffmpegPath], {
        stdio: ['pipe', 'pipe', 'pipe']
    })

    pythonProcess.stdout.on('data', (data) => {
        console.log('[Python]', data.toString())
    })

    pythonProcess.stderr.on('data', (data) => {
        console.error('[Python Error]', data.toString())
    })

    pythonProcess.on('close', (code) => {
        console.log(`Python process exited with code ${code}`)
    })
}

function createWindow() {
    const win = new BrowserWindow({
        width: 800,
        height: 600
    })
    win.loadFile('index.html')
}

app.whenReady().then(() => {
    createWindow()
    startPythonDetector()
})

// Kill Python when app closes
app.on('before-quit', () => {
    if (pythonProcess) {
        pythonProcess.kill()
    }
})