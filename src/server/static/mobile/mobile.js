/**
 * IRIS-BOX Mobile Companion Client
 * Air-gapped, zero-CDN client logic:
 * - Cryptographic LAN PIN pairing with persistent device token storage
 * - Mobile Web Audio API 16,000 Hz 16-bit Linear PCM audio streamer
 * - Duplex audio playback with OutboundAudioFlushPayload barge-in interruption
 * - Real-time LAN Server-Sent Events (SSE) notification listener
 * - Progressive Web App Service Worker registration
 */

// State
let deviceToken = localStorage.getItem('iris_device_token') || null;
let deviceId = localStorage.getItem('iris_device_id') || null;
let audioContext = null;
let mediaStream = null;
let scriptProcessor = null;
let isRecording = false;
let socket = null;
let eventSource = null;
let audioQueue = [];
let currentAudioSource = null;
let isPlayingAudio = false;

// DOM Elements
const pairingScreen = document.getElementById('pairingScreen');
const companionScreen = document.getElementById('companionScreen');
const pinInput = document.getElementById('pinInput');
const pairBtn = document.getElementById('pairBtn');
const pairError = document.getElementById('pairError');
const micBtn = document.getElementById('micBtn');
const micStatus = document.getElementById('micStatus');
const connectionStatus = document.getElementById('connectionStatus');
const transcriptBox = document.getElementById('transcriptBox');
const notificationBadge = document.getElementById('notificationBadge');
const notificationList = document.getElementById('notificationList');
const clearNotifsBtn = document.getElementById('clearNotifsBtn');
const disconnectBtn = document.getElementById('disconnectBtn');
const installPrompt = document.getElementById('installPrompt');
const installBtn = document.getElementById('installBtn');
const dismissInstallBtn = document.getElementById('dismissInstallBtn');

// 1. Initialize UI and Service Worker
window.addEventListener('DOMContentLoaded', async () => {
    initServiceWorker();
    setupPwaInstallPrompt();

    if (deviceToken && deviceId) {
        showCompanion();
        initCompanionServices();
    } else {
        showPairing();
    }

    setupEventListeners();
});

// Service Worker Registration (Air-gapped)
function initServiceWorker() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/mobile/sw.js')
            .then(reg => {
                console.log('[IRIS Mobile] Service Worker registered with scope:', reg.scope);
            })
            .catch(err => {
                console.warn('[IRIS Mobile] Service Worker registration failed:', err);
            });
    }
}

// PWA Install prompt handling
let deferredPrompt = null;
function setupPwaInstallPrompt() {
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPrompt = e;
        if (installPrompt) {
            installPrompt.classList.remove('hidden');
        }
    });

    if (installBtn) {
        installBtn.addEventListener('click', async () => {
            if (deferredPrompt) {
                deferredPrompt.prompt();
                const choice = await deferredPrompt.userChoice;
                if (choice.outcome === 'accepted') {
                    console.log('[IRIS Mobile] PWA installation accepted');
                }
                deferredPrompt = null;
                if (installPrompt) installPrompt.classList.add('hidden');
            }
        });
    }

    if (dismissInstallBtn) {
        dismissInstallBtn.addEventListener('click', () => {
            if (installPrompt) installPrompt.classList.add('hidden');
        });
    }
}

function showPairing() {
    if (pairingScreen) pairingScreen.classList.remove('hidden');
    if (companionScreen) companionScreen.classList.add('hidden');
    if (pinInput) {
        pinInput.value = '';
        pinInput.focus();
    }
}

function showCompanion() {
    if (pairingScreen) pairingScreen.classList.add('hidden');
    if (companionScreen) companionScreen.classList.remove('hidden');
}

// 2. Event Listeners Setup
function setupEventListeners() {
    if (pairBtn) {
        pairBtn.addEventListener('click', handlePair);
    }

    if (pinInput) {
        pinInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') handlePair();
        });
    }

    if (micBtn) {
        micBtn.addEventListener('click', toggleMicrophone);
        micBtn.addEventListener('touchstart', (e) => {
            // Touchstart fulfills Web Audio API requirement for mobile Safari/Chrome
            if (!audioContext) {
                initAudioContext();
            }
        }, { passive: true });
    }

    if (clearNotifsBtn) {
        clearNotifsBtn.addEventListener('click', () => {
            if (notificationList) notificationList.innerHTML = '';
            updateNotificationCount(0);
        });
    }

    if (disconnectBtn) {
        disconnectBtn.addEventListener('click', handleDisconnect);
    }
}

// 3. Cryptographic LAN Pairing Flow
async function handlePair() {
    const pin = pinInput.value.trim();
    if (!pin || pin.length !== 6 || !/^\d{6}$/.test(pin)) {
        showPairError('Please enter a valid 6-digit numeric PIN.');
        return;
    }

    setPairLoading(true);
    showPairError('');

    try {
        const response = await fetch('/api/pairing/pair', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                pin: pin,
                device_type: 'mobile',
                user_agent: navigator.userAgent
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Pairing failed');
        }

        deviceToken = data.device_token;
        deviceId = data.device_id;
        localStorage.setItem('iris_device_token', deviceToken);
        localStorage.setItem('iris_device_id', deviceId);

        showCompanion();
        initCompanionServices();
        appendTranscript('system', 'Connected to IRIS-BOX via secure LAN pairing.');
    } catch (err) {
        showPairError(err.message || 'Pairing failed. Check PIN and retry.');
    } finally {
        setPairLoading(false);
    }
}

function showPairError(msg) {
    if (pairError) {
        pairError.textContent = msg;
        pairError.style.display = msg ? 'block' : 'none';
    }
}

function setPairLoading(loading) {
    if (pairBtn) {
        pairBtn.disabled = loading;
        pairBtn.textContent = loading ? 'Pairing...' : 'Pair Satellite';
    }
}

function handleDisconnect() {
    stopRecording();
    abortAudioPlayback();
    if (eventSource) eventSource.close();
    if (socket) socket.close();

    localStorage.removeItem('iris_device_token');
    localStorage.removeItem('iris_device_id');
    deviceToken = null;
    deviceId = null;

    showPairing();
}

// 4. Companion Services (WebSocket & SSE Stream)
function initCompanionServices() {
    initWebSocket();
    initNotificationStream();
}

// WebSocket setup for duplex audio and transcripts
function initWebSocket() {
    if (socket && socket.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(deviceToken)}`;

    try {
        socket = new WebSocket(wsUrl);
        socket.binaryType = 'arraybuffer';

        socket.onopen = () => {
            updateConnectionStatus('online', 'Connected');
            console.log('[IRIS Mobile] WebSocket connected');
        };

        socket.onmessage = async (event) => {
            if (typeof event.data === 'string') {
                handleTextMessage(event.data);
            } else if (event.data instanceof ArrayBuffer) {
                handleBinaryAudio(event.data);
            }
        };

        socket.onerror = (err) => {
            console.warn('[IRIS Mobile] WebSocket error:', err);
            updateConnectionStatus('offline', 'Error');
        };

        socket.onclose = () => {
            updateConnectionStatus('offline', 'Disconnected');
            // Reconnect after 3s if still paired
            if (deviceToken) {
                setTimeout(initWebSocket, 3000);
            }
        };
    } catch (err) {
        console.error('[IRIS Mobile] Failed to initialize WebSocket:', err);
    }
}

function handleTextMessage(dataStr) {
    try {
        const payload = JSON.parse(dataStr);
        const type = payload.type;

        // Duplex Barge-In Flush Handling: server detected user speech energy or client abort
        if (type === 'outbound_audio_flush' || type === 'barge_in_flush') {
            console.log('[IRIS Mobile] Received OutboundAudioFlushPayload -> aborting speaker output');
            abortAudioPlayback();
            return;
        }

        if (type === 'stt_transcript') {
            appendTranscript('user', payload.text || payload.transcript);
        } else if (type === 'llm_token') {
            appendAssistantToken(payload.token);
        } else if (type === 'assistant_reply' || type === 'response_text') {
            appendTranscript('assistant', payload.text || payload.content);
        } else if (type === 'proactive_announcement') {
            appendTranscript('system', `[Announcement] ${payload.text}`);
        }
    } catch {
        // Plain text response fallback
        appendTranscript('assistant', dataStr);
    }
}

// 5. Mobile Web Audio API - Mic Capture (16kHz mono Linear PCM)
function initAudioContext() {
    if (!audioContext) {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        audioContext = new AudioCtx({ sampleRate: 16000 });
    }
    if (audioContext.state === 'suspended') {
        audioContext.resume();
    }
}

async function toggleMicrophone() {
    if (isRecording) {
        stopRecording();
    } else {
        await startRecording();
    }
}

async function startRecording() {
    initAudioContext();
    if (audioContext.state === 'suspended') {
        await audioContext.resume();
    }

    // Flush any ongoing audio playback so user speaks into silence
    abortAudioPlayback();

    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                channelCount: 1,
                sampleRate: 16000,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            }
        });

        const source = audioContext.createMediaStreamSource(mediaStream);
        // 2048 samples @ 16kHz is ~128ms chunks
        scriptProcessor = audioContext.createScriptProcessor(2048, 1, 1);

        scriptProcessor.onaudioprocess = (e) => {
            if (!isRecording) return;
            const inputData = e.inputBuffer.getChannelData(0);
            
            // Convert Float32Array [-1.0, 1.0] to Int16Array [-32768, 32767]
            const pcm16 = new Int16Array(inputData.length);
            for (let i = 0; i < inputData.length; i++) {
                const s = Math.max(-1, Math.min(1, inputData[i]));
                pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }

            // Stream raw PCM chunk over WebSocket
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(pcm16.buffer);
            }
        };

        source.connect(scriptProcessor);
        scriptProcessor.connect(audioContext.destination);

        isRecording = true;
        updateMicUI(true);
    } catch (err) {
        console.error('[IRIS Mobile] Microphone access error:', err);
        alert('Could not access microphone. Ensure microphone permissions are granted.');
        stopRecording();
    }
}

function stopRecording() {
    isRecording = false;
    updateMicUI(false);

    if (scriptProcessor) {
        scriptProcessor.disconnect();
        scriptProcessor = null;
    }

    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
}

function updateMicUI(active) {
    if (micBtn) {
        if (active) {
            micBtn.classList.add('recording');
        } else {
            micBtn.classList.remove('recording');
        }
    }
    if (micStatus) {
        micStatus.textContent = active ? 'Listening (16kHz PCM)...' : 'Tap to Speak';
    }
}

// 6. Audio Playback & Barge-in Flushing
function handleBinaryAudio(arrayBuffer) {
    initAudioContext();
    // Convert 16kHz Int16 PCM back to Float32 AudioBuffer
    const int16View = new Int16Array(arrayBuffer);
    const float32Data = new Float32Array(int16View.length);
    for (let i = 0; i < int16View.length; i++) {
        float32Data[i] = int16View[i] / 32768.0;
    }

    const audioBuffer = audioContext.createBuffer(1, float32Data.length, 16000);
    audioBuffer.getChannelData(0).set(float32Data);

    audioQueue.push(audioBuffer);
    if (!isPlayingAudio) {
        playNextAudioQueueItem();
    }
}

function playNextAudioQueueItem() {
    if (audioQueue.length === 0) {
        isPlayingAudio = false;
        currentAudioSource = null;
        return;
    }

    isPlayingAudio = true;
    const buffer = audioQueue.shift();
    currentAudioSource = audioContext.createBufferSource();
    currentAudioSource.buffer = buffer;
    currentAudioSource.connect(audioContext.destination);

    currentAudioSource.onended = () => {
        playNextAudioQueueItem();
    };

    currentAudioSource.start();
}

function abortAudioPlayback() {
    audioQueue = [];
    if (currentAudioSource) {
        try {
            currentAudioSource.stop();
            currentAudioSource.disconnect();
        } catch {}
        currentAudioSource = null;
    }
    isPlayingAudio = false;
}

// 7. LAN Server-Sent Events (SSE) Push Notifications
function initNotificationStream() {
    if (eventSource) {
        eventSource.close();
    }

    if (!deviceToken) return;

    const sseUrl = `/api/notifications/stream?token=${encodeURIComponent(deviceToken)}`;
    eventSource = new EventSource(sseUrl);

    eventSource.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);
            if (data.type === 'keepalive') return;
            addNotificationCard(data);
        } catch (err) {
            console.warn('[IRIS Mobile] Failed to parse SSE event:', err);
        }
    };

    eventSource.onerror = (err) => {
        console.warn('[IRIS Mobile] SSE Stream error/disconnected, reconnecting...');
    };
}

let notificationCount = 0;
function addNotificationCard(notif) {
    if (!notificationList) return;

    notificationCount++;
    updateNotificationCount(notificationCount);

    const card = document.createElement('div');
    card.className = `notif-card ${notif.severity || 'info'}`;

    const timestamp = notif.timestamp ? new Date(notif.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();

    card.innerHTML = `
        <div class="notif-header">
            <span class="notif-topic">${escapeHtml(notif.topic || 'System')}</span>
            <span class="notif-time">${timestamp}</span>
        </div>
        <div class="notif-body">${escapeHtml(notif.message || '')}</div>
    `;

    notificationList.prepend(card);

    // If screen supports Vibration API, trigger subtle haptic feedback
    if (navigator.vibrate) {
        navigator.vibrate(50);
    }
}

function updateNotificationCount(count) {
    if (notificationBadge) {
        notificationBadge.textContent = count > 0 ? count : '';
        notificationBadge.style.display = count > 0 ? 'inline-flex' : 'none';
    }
}

// 8. Transcript UI Helper
let activeAssistantParagraph = null;

function appendTranscript(sender, text) {
    if (!transcriptBox) return;

    activeAssistantParagraph = null;
    const msgDiv = document.createElement('div');
    msgDiv.className = `transcript-msg ${sender}`;
    msgDiv.textContent = text;
    transcriptBox.appendChild(msgDiv);
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
}

function appendAssistantToken(token) {
    if (!transcriptBox) return;

    if (!activeAssistantParagraph) {
        activeAssistantParagraph = document.createElement('div');
        activeAssistantParagraph.className = 'transcript-msg assistant';
        transcriptBox.appendChild(activeAssistantParagraph);
    }

    activeAssistantParagraph.textContent += token;
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
}

function updateConnectionStatus(status, label) {
    if (!connectionStatus) return;
    connectionStatus.className = `status-pill ${status}`;
    const dot = connectionStatus.querySelector('.status-dot');
    const text = connectionStatus.querySelector('.status-text');
    if (text) text.textContent = label;
}

function escapeHtml(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
