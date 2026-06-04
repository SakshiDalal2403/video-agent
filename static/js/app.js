function createClientId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
        return window.crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const state = {
    pollTimer: null,
    pollFailures: 0,
    processing: false,
    tabId: window.sessionStorage.getItem("video_agent_tab_id") || createClientId(),
    activeRunId: window.sessionStorage.getItem("video_agent_run_id") || "",
    recording: false,
    recordingStream: null,
    audioContext: null,
    recorderSource: null,
    recorderProcessor: null,
    recorderSilence: null,
    recordingSampleRate: 0,
    recordedChunks: [],
    recordedFile: null,
    recordingUrl: "",
};

window.sessionStorage.setItem("video_agent_tab_id", state.tabId);

const elements = {
    analyzeForm: document.getElementById("analyze-form"),
    source: document.getElementById("source"),
    mediaFile: document.getElementById("media-file"),
    fileName: document.getElementById("file-name"),
    recordStartBtn: document.getElementById("record-start-btn"),
    recordStopBtn: document.getElementById("record-stop-btn"),
    recordDiscardBtn: document.getElementById("record-discard-btn"),
    recordingStatus: document.getElementById("recording-status"),
    recordingPreview: document.getElementById("recording-preview"),
    language: document.getElementById("language"),
    languageOptions: document.querySelectorAll(".language-option"),
    analyzeBtn: document.getElementById("analyze-btn"),
    statusChip: document.getElementById("status-chip"),
    pipelineSteps: document.getElementById("pipeline-steps"),
    messageBar: document.getElementById("message-bar"),
    emptyState: document.getElementById("empty-state"),
    resultsSection: document.getElementById("results-section"),
    resultTitle: document.getElementById("result-title"),
    summaryContent: document.getElementById("summary-content"),
    transcriptContent: document.getElementById("transcript-content"),
    actionItemsContent: document.getElementById("action-items-content"),
    keyDecisionsContent: document.getElementById("key-decisions-content"),
    openQuestionsContent: document.getElementById("open-questions-content"),
    chatHistory: document.getElementById("chat-history"),
    chatForm: document.getElementById("chat-form"),
    chatInput: document.getElementById("chat-input"),
    sendBtn: document.getElementById("send-btn"),
    clearChatBtn: document.getElementById("clear-chat-btn"),
};

const pipelineIcons = {
    audio: "♪",
    transcript: "T",
    title: "#",
    summary: "S",
    extract: "✓",
    rag: "?",
};

function syncLanguageToggle(value) {
    elements.languageOptions.forEach((option) => {
        option.classList.toggle("active", option.dataset.language === value);
    });
}

function setMessage(message, type = "info") {
    if (!message) {
        elements.messageBar.className = "message-bar hidden";
        elements.messageBar.textContent = "";
        return;
    }

    elements.messageBar.className = `message-bar ${type}`;
    elements.messageBar.textContent = message;
}

function setStatusChip(mode, label) {
    elements.statusChip.className = "status-chip";
    if (mode) {
        elements.statusChip.classList.add(mode);
    }
    elements.statusChip.textContent = label;
}

function renderPipelineSteps(stepState = {}, labels = {}) {
    const order = ["audio", "transcript", "title", "summary", "extract", "rag"];
    elements.pipelineSteps.innerHTML = "";

    order.forEach((key) => {
        const status = stepState[key] || "pending";
        const card = document.createElement("div");
        card.className = `pipeline-step ${status}`;

        const left = document.createElement("div");
        left.className = "pipeline-step-left";

        const marker = document.createElement("span");
        marker.className = "step-marker";
        marker.textContent = status === "done" ? "✓" : pipelineIcons[key] || "";

        const textWrap = document.createElement("div");

        const title = document.createElement("div");
        title.className = "pipeline-step-title";
        title.textContent = labels[key] || key;

        const sub = document.createElement("div");
        sub.className = "pipeline-step-state";
        sub.textContent = status.charAt(0).toUpperCase() + status.slice(1);

        textWrap.appendChild(title);
        textWrap.appendChild(sub);
        left.appendChild(marker);
        left.appendChild(textWrap);
        card.appendChild(left);
        elements.pipelineSteps.appendChild(card);
    });
}

function updateResultVisibility(hasResult) {
    elements.resultsSection.classList.toggle("hidden", !hasResult);
}

function setText(el, value) {
    el.textContent = value || "";
}

function renderResult(result) {
    if (!result) {
        updateResultVisibility(false);
        return;
    }

    updateResultVisibility(true);
    setText(elements.resultTitle, result.title || "Untitled Session");
    setText(elements.summaryContent, result.summary || "");
    setText(elements.transcriptContent, result.transcript || "");
    setText(elements.actionItemsContent, result.action_items || "");
    setText(elements.keyDecisionsContent, result.key_decisions || "");
    setText(elements.openQuestionsContent, result.open_questions || "");
}

function renderChat(chatHistory = []) {
    elements.chatHistory.innerHTML = "";

    if (!chatHistory.length) {
        const empty = document.createElement("div");
        empty.className = "chat-empty";

        const text = document.createElement("p");
        text.textContent = "No messages yet. Ask anything about the transcript.";

        empty.appendChild(text);
        elements.chatHistory.appendChild(empty);
        return;
    }

    chatHistory.forEach((message) => {
        const wrap = document.createElement("div");
        wrap.className = `chat-message ${message.role}`;

        const role = document.createElement("div");
        role.className = "chat-role";
        role.textContent = message.role === "user" ? "You" : "Assistant";

        const bubble = document.createElement("div");
        bubble.className = "chat-bubble";
        bubble.textContent = message.content;

        wrap.appendChild(role);
        wrap.appendChild(bubble);
        elements.chatHistory.appendChild(wrap);
    });

    elements.chatHistory.scrollTop = elements.chatHistory.scrollHeight;
}

function setProcessingUI(processing) {
    state.processing = processing;
    elements.analyzeBtn.disabled = processing;
    elements.sendBtn.disabled = processing;
    elements.clearChatBtn.disabled = processing;
    elements.recordStartBtn.disabled = processing || state.recording;
    elements.recordStopBtn.disabled = processing || !state.recording;
    elements.recordDiscardBtn.disabled = processing || !state.recordedFile;

    if (processing) {
        setStatusChip("running", "Running");
    }
}

async function fetchState() {
    const params = new URLSearchParams({ tab_id: state.tabId });
    if (state.activeRunId) {
        params.set("run_id", state.activeRunId);
    }

    const response = await fetch(`/api/state?${params.toString()}`);
    if (!response.ok) {
        throw new Error("State refresh failed.");
    }
    const data = await response.json();
    state.pollFailures = 0;
    applyState(data);
    return data;
}

function applyState(data) {
    renderPipelineSteps(data.pipeline_steps, data.pipeline_labels);
    renderResult(data.result);
    renderChat(data.chat_history);

    if (data.error) {
        setMessage(data.error, "error");
        setStatusChip("error", "Error");
    } else if (data.processing) {
        setMessage("Pipeline running. The UI is polling live step status.", "info");
        setStatusChip("running", "Running");
    } else if (data.pipeline_done) {
        setMessage("Analysis complete. You can now review the results and chat with the transcript.", "info");
        setStatusChip("done", "Done");
    } else {
        setMessage("", "info");
        setStatusChip("", "Idle");
    }

    setProcessingUI(Boolean(data.processing));

    if (data.processing) {
        startPolling();
    } else {
        stopPolling();
    }
}

function startPolling() {
    if (state.pollTimer) {
        return;
    }

    state.pollTimer = window.setInterval(async () => {
        try {
            await fetchState();
        } catch (error) {
            state.pollFailures += 1;
            console.error("Unable to refresh pipeline status.", error);

            if (state.pollFailures >= 20) {
                setMessage("Unable to refresh pipeline status. Please reload the page and check the latest run state.", "error");
                stopPolling();
                setProcessingUI(false);
                return;
            }

            setMessage("Refreshing pipeline status...", "info");
        }
    }, 1500);
}

function stopPolling() {
    if (!state.pollTimer) {
        return;
    }

    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
}

async function postJSON(url, payload) {
    const response = await fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
    });

    let data;
    try {
        data = await response.json();
    } catch (error) {
        throw new Error("Server returned an invalid response.");
    }

    if (!response.ok) {
        throw new Error(data.error || "Request failed.");
    }

    return data;
}

async function postAnalyze(source, language, file) {
    if (!file) {
        return postJSON("/api/analyze", { source, language, tab_id: state.tabId });
    }

    const formData = new FormData();
    formData.append("source", source);
    formData.append("language", language);
    formData.append("tab_id", state.tabId);
    formData.append("file", file);

    const response = await fetch("/api/analyze", {
        method: "POST",
        body: formData,
    });

    let data;
    try {
        data = await response.json();
    } catch (error) {
        throw new Error("Server returned an invalid response.");
    }

    if (!response.ok) {
        throw new Error(data.error || "Request failed.");
    }

    return data;
}

function clearRecording() {
    if (state.recordingUrl) {
        URL.revokeObjectURL(state.recordingUrl);
    }

    state.recordedChunks = [];
    state.recordedFile = null;
    state.recordingUrl = "";
    elements.recordingPreview.removeAttribute("src");
    elements.recordingPreview.classList.add("hidden");
    elements.recordingStatus.textContent = "No microphone recording yet.";
    setProcessingUI(state.processing);
}

function encodeWav(samples, sampleRate) {
    const bytesPerSample = 2;
    const channelCount = 1;
    const dataSize = samples.length * bytesPerSample;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);

    function writeString(offset, value) {
        for (let i = 0; i < value.length; i += 1) {
            view.setUint8(offset + i, value.charCodeAt(i));
        }
    }

    writeString(0, "RIFF");
    view.setUint32(4, 36 + dataSize, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, channelCount, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * channelCount * bytesPerSample, true);
    view.setUint16(32, channelCount * bytesPerSample, true);
    view.setUint16(34, 16, true);
    writeString(36, "data");
    view.setUint32(40, dataSize, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i += 1) {
        const sample = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
        offset += 2;
    }

    return new Blob([view], { type: "audio/wav" });
}

function mergeAudioChunks(chunks) {
    const totalLength = chunks.reduce((total, chunk) => total + chunk.length, 0);
    const samples = new Float32Array(totalLength);
    let offset = 0;

    chunks.forEach((chunk) => {
        samples.set(chunk, offset);
        offset += chunk.length;
    });

    return samples;
}

function resetRecordingNodes() {
    if (state.recorderProcessor) {
        state.recorderProcessor.disconnect();
    }
    if (state.recorderSource) {
        state.recorderSource.disconnect();
    }
    if (state.recorderSilence) {
        state.recorderSilence.disconnect();
    }
    if (state.recordingStream) {
        state.recordingStream.getTracks().forEach((track) => track.stop());
    }
    if (state.audioContext) {
        state.audioContext.close();
    }

    state.recording = false;
    state.recordingStream = null;
    state.audioContext = null;
    state.recorderSource = null;
    state.recorderProcessor = null;
    state.recorderSilence = null;
}

async function startRecording() {
    const AudioContextConstructor = window.AudioContext || window.webkitAudioContext;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !AudioContextConstructor) {
        setMessage("Microphone recording is not supported in this browser.", "error");
        return;
    }

    try {
        clearRecording();
        elements.mediaFile.value = "";
        elements.fileName.textContent = "No file selected";

        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const audioContext = new AudioContextConstructor();
        const source = audioContext.createMediaStreamSource(stream);
        const processor = audioContext.createScriptProcessor(4096, 1, 1);
        const silence = audioContext.createGain();

        silence.gain.value = 0;
        state.recording = true;
        state.recordingStream = stream;
        state.audioContext = audioContext;
        state.recorderSource = source;
        state.recorderProcessor = processor;
        state.recorderSilence = silence;
        state.recordingSampleRate = audioContext.sampleRate;
        state.recordedChunks = [];
        elements.recordingStatus.textContent = "Recording... speak now.";
        setProcessingUI(state.processing);

        processor.onaudioprocess = (event) => {
            if (!state.recording) {
                return;
            }

            const input = event.inputBuffer.getChannelData(0);
            state.recordedChunks.push(new Float32Array(input));
        };

        source.connect(processor);
        processor.connect(silence);
        silence.connect(audioContext.destination);
        setMessage("Microphone recording started.", "info");
    } catch (error) {
        resetRecordingNodes();
        setProcessingUI(state.processing);
        setMessage("Unable to access microphone. Please allow microphone permission.", "error");
    }
}

function stopRecording() {
    if (!state.recording) {
        return;
    }

    elements.recordingStatus.textContent = "Preparing recording...";

    const samples = mergeAudioChunks(state.recordedChunks);
    const blob = encodeWav(samples, state.recordingSampleRate || 44100);
    const fileName = `microphone-recording-${Date.now()}.wav`;

    resetRecordingNodes();

    state.recordedFile = new File([blob], fileName, { type: "audio/wav" });
    state.recordingUrl = URL.createObjectURL(blob);
    elements.recordingPreview.src = state.recordingUrl;
    elements.recordingPreview.classList.remove("hidden");
    elements.recordingStatus.textContent = `Ready to analyze: ${state.recordedFile.name}`;
    elements.fileName.textContent = state.recordedFile.name;
    setProcessingUI(state.processing);
}

elements.analyzeForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const source = elements.source.value.trim();
    const file = elements.mediaFile.files[0] || state.recordedFile || null;
    const language = elements.language.value;

    if (!source && !file) {
        setMessage("Please enter a YouTube URL, file path, choose an audio/video file, or record microphone audio.", "error");
        return;
    }

    try {
        setMessage("Starting pipeline...", "info");
        setProcessingUI(true);
        renderPipelineSteps({}, {});
        const data = await postAnalyze(source, language, file);
        if (data.run_id) {
            state.activeRunId = data.run_id;
            window.sessionStorage.setItem("video_agent_run_id", data.run_id);
        }
        await fetchState();
    } catch (error) {
        setProcessingUI(false);
        setMessage(error.message, "error");
        setStatusChip("error", "Error");
    }
});

elements.mediaFile.addEventListener("change", () => {
    const file = elements.mediaFile.files[0];
    if (file) {
        clearRecording();
    }
    elements.fileName.textContent = file ? file.name : "No file selected";
});

elements.recordStartBtn.addEventListener("click", startRecording);
elements.recordStopBtn.addEventListener("click", stopRecording);
elements.recordDiscardBtn.addEventListener("click", clearRecording);

elements.chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const question = elements.chatInput.value.trim();
    if (!question) {
        return;
    }

    elements.sendBtn.disabled = true;
    setMessage("Fetching answer from the transcript context...", "info");

    try {
        const data = await postJSON("/api/chat", {
            question,
            tab_id: state.tabId,
            run_id: state.activeRunId,
        });
        renderChat(data.chat_history);
        elements.chatInput.value = "";
        setMessage("Answer generated from the current meeting transcript.", "info");
    } catch (error) {
        setMessage(error.message, "error");
    } finally {
        elements.sendBtn.disabled = false;
    }
});

elements.clearChatBtn.addEventListener("click", async () => {
    try {
        await postJSON("/api/chat/clear", {
            tab_id: state.tabId,
            run_id: state.activeRunId,
        });
        renderChat([]);
        setMessage("Chat history cleared.", "info");
    } catch (error) {
        setMessage(error.message, "error");
    }
});

elements.languageOptions.forEach((option) => {
    option.addEventListener("click", () => {
        elements.language.value = option.dataset.language;
        syncLanguageToggle(elements.language.value);
    });
});

window.addEventListener("load", async () => {
    renderPipelineSteps({}, {});
    syncLanguageToggle(elements.language.value);
    try {
        await fetchState();
    } catch (error) {
        setMessage("Unable to load app state.", "error");
        setStatusChip("error", "Error");
    }
});
