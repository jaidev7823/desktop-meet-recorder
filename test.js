const { Recorder } = require('@arcsine/screen-recorder');
const { execSync } = require('child_process');
const readline = require('readline');

// Fixed parser for FFmpeg dshow output
function listAudioDevices() {
  try {
    const output = execSync('ffmpeg -f dshow -list_devices true -i dummy 2>&1', { encoding: 'utf8' });
    const audioDevices = [];
    
    // Look for lines with (audio) type
    const lines = output.split('\n');
    for (const line of lines) {
      if (line.includes('(audio)')) {
        // Extract device name between quotes: "Microphone (Audio Array AM-C1 Device)"
        const match = line.match(/\[dshow @ [^\]]+\] "(.+?)" \(audio\)/);
        if (match) {
          audioDevices.push(match[1]);
        }
      }
    }
    
    // Fallback: manually parse from your output
    if (audioDevices.length === 0) {
      // Hardcode from your FFmpeg output above
      audioDevices.push('Microphone (Audio Array AM-C1 Device)');
      // Add Stereo Mix if you enable it later
    }
    
    return audioDevices;
  } catch (error) {
    console.error('FFmpeg error:', error.message);
    return [];
  }
}

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

(async () => {
  console.log('🔊 Scanning audio devices...\n');
  
  const devices = listAudioDevices();
  
  if (devices.length === 0) {
    console.log('❌ No audio devices detected automatically.');
    console.log('📋 Available from your FFmpeg output:');
    console.log('1. Microphone (Audio Array AM-C1 Device)');
    console.log('2. OBS Virtual Camera (video only)');
    console.log('\n⏭️  Press Enter to continue with manual selection...');
    rl.question('', () => selectDevice(rl));
  } else {
    showDevices(devices, rl);
  }
})();

function showDevices(devices, rl) {
  console.log('📱 Available Audio Devices:');
  devices.forEach((device, index) => {
    console.log(`${index + 1}. ${device}`);
  });
  console.log('0. No audio');
  
  rl.question('\nSelect device number: ', (input) => {
    const choice = parseInt(input);
    if (choice === 0) {
      startRecording({}, rl);
    } else if (choice > 0 && choice <= devices.length) {
      startRecording({ audioDevice: devices[choice - 1] }, rl);
    } else {
      console.log('❌ Invalid choice');
      rl.close();
    }
  });
}

function selectDevice(rl) {
  console.log('\n📱 Manual Selection:');
  console.log('1. Microphone (Audio Array AM-C1 Device)');
  console.log('0. No audio');
  
  rl.question('Select (1 or 0): ', (input) => {
    const choice = parseInt(input);
    if (choice === 1) {
      startRecording({ audioDevice: 'Microphone (Audio Array AM-C1 Device)' }, rl);
    } else {
      startRecording({}, rl);
    }
  });
}

async function startRecording(audioConfig, rl) {
  try {
    rl.close();
    
    const filename = `./recording-${Date.now()}.mp4`;
    console.log(`\n🎥 Recording to: ${filename}`);
    
    const rec = await Recorder.recordActiveWindow({
      file: filename,
      fps: 30,
      video: 'gdigrab',
      audioBitrate: 128,
      ...audioConfig
    });
    
    console.log('⏹️  Press Ctrl+C to stop');
    
    process.on('SIGINT', async () => {
      console.log('\n⏳ Saving...');
      await rec.stop();
      console.log('✅ Done!');
      process.exit(0);
    });
    
  } catch (error) {
    console.error('❌ Error:', error.message);
    rl.close();
    process.exit(1);
  }
}
