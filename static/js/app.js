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
    inputRevealed: false,
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
    recordingWave: document.getElementById("recording-wave"),
    language: document.getElementById("language"),
    languageOptions: document.querySelectorAll(".language-option"),
    sourceModeButtons: document.querySelectorAll(".source-mode-card"),
    sourceModePanels: document.querySelectorAll(".source-mode-panel"),
    sourceInputStep: document.querySelector(".source-input-step"),
    analyzeBtn: document.getElementById("analyze-btn"),
    statusChip: document.getElementById("status-chip"),
    pipelineStarting: document.getElementById("pipeline-starting"),
    pipelineSteps: document.getElementById("pipeline-steps"),
    messageBar: document.getElementById("message-bar"),
    processingState: document.getElementById("processing-state"),
    emptyState: document.getElementById("empty-state"),
    resultsSection: document.getElementById("results-section"),
    resultTitle: document.getElementById("result-title"),
    summaryContent: document.getElementById("summary-content"),
    transcriptContent: document.getElementById("transcript-content"),
    actionItemsContent: document.getElementById("action-items-content"),
    keyDecisionsContent: document.getElementById("key-decisions-content"),
    openQuestionsContent: document.getElementById("open-questions-content"),
    resultViews: document.querySelectorAll(".result-view"),
    resultNavButtons: document.querySelectorAll(".result-nav-btn"),
    resultModal: document.getElementById("result-modal"),
    resultModalTitle: document.getElementById("result-modal-title"),
    resultModalCloseButtons: document.querySelectorAll("[data-modal-close]"),
    startNewBtn: document.getElementById("start-new-btn"),
    chatHistory: document.getElementById("chat-history"),
    chatForm: document.getElementById("chat-form"),
    chatInput: document.getElementById("chat-input"),
    sendBtn: document.getElementById("send-btn"),
    clearChatBtn: document.getElementById("clear-chat-btn"),
    inlineTranscript: document.getElementById("inline-transcript"),
    inlineTranscriptContent: document.getElementById("inline-transcript-content"),
    transcriptToggleBtn: document.getElementById("transcript-toggle-btn"),
    heroPanel: document.getElementById("hero-panel"),
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

function setSourceMode(mode) {
    if (elements.sourceInputStep) {
        elements.sourceInputStep.classList.toggle("hidden", !mode);
    }

    elements.sourceModeButtons.forEach((button) => {
        const isActive = button.dataset.sourceMode === mode;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
    });

    elements.sourceModePanels.forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.sourcePanel === mode);
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

    // Check if any step has real progress yet
    const hasProgress = order.some((key) => stepState[key] === "active" || stepState[key] === "done");

    if (hasProgress) {
        // Real step data arrived — swap starting message for actual steps
        elements.pipelineStarting.classList.add("hidden");
        elements.pipelineSteps.classList.remove("hidden");
    }

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
        if (status === "active") {
            sub.textContent = "In progress";
        } else if (status === "done") {
            sub.textContent = "Done";
        } else {
            sub.textContent = "Waiting";
        }

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
    if (elements.heroPanel) {
        elements.heroPanel.classList.toggle("hidden", hasResult);
    }
}

function updateProcessingVisibility(processing) {
    elements.processingState.classList.toggle("hidden", !processing);
}

function updateInputVisibility(hasResult, processing = state.processing) {
    elements.emptyState.classList.toggle("hidden", processing || (hasResult && !state.inputRevealed));
}

function setText(el, value) {
    if (el) {
        el.textContent = value || "";
    }
}

function parseMarkdown(text) {
    if (!text) {
        return "";
    }

    // Escape HTML first to prevent XSS
    let html = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    // Replace bold text **bold** with <strong>bold</strong>
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

    // Split text by lines to parse lists
    const lines = html.split("\n");
    const processedLines = [];
    let insideList = false;

    lines.forEach((line) => {
        const trimmed = line.trim();
        // Check if line starts with markdown bullets "- " or "* "
        if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
            const isSub = line.startsWith("  ") || line.startsWith("\t");
            const content = trimmed.substring(2);
            
            if (!insideList) {
                processedLines.push('<ul class="markdown-list">');
                insideList = true;
            }
            
            processedLines.push(`<li class="${isSub ? 'sub-bullet' : 'main-bullet'}">${content}</li>`);
        } else {
            if (insideList) {
                processedLines.push("</ul>");
                insideList = false;
            }
            
            if (trimmed) {
                processedLines.push(`<p class="markdown-para">${line}</p>`);
            } else {
                processedLines.push('<div class="markdown-space"></div>');
            }
        }
    });

    if (insideList) {
        processedLines.push("</ul>");
    }

    return processedLines.join("\n");
}

function setHTMLContent(el, value) {
    if (el) {
        el.innerHTML = parseMarkdown(value);
    }
}

function setupRecordingWave() {
    if (!elements.recordingWave || elements.recordingWave.children.length) {
        return;
    }

    for (let index = 0; index < 28; index += 1) {
        const bar = document.createElement("span");
        bar.className = "recording-wave-bar";
        bar.style.height = "8px";
        elements.recordingWave.appendChild(bar);
    }
}

function setRecordingWaveVisible(visible) {
    elements.recordingWave.classList.toggle("hidden", !visible);
}

function updateRecordingWave(samples) {
    if (!elements.recordingWave || elements.recordingWave.classList.contains("hidden")) {
        return;
    }

    const bars = Array.from(elements.recordingWave.children);
    if (!bars.length) {
        return;
    }

    const chunkSize = Math.max(1, Math.floor(samples.length / bars.length));
    bars.forEach((bar, index) => {
        let sum = 0;
        const start = index * chunkSize;
        const end = Math.min(samples.length, start + chunkSize);
        for (let sampleIndex = start; sampleIndex < end; sampleIndex += 1) {
            sum += Math.abs(samples[sampleIndex]);
        }
        const average = sum / Math.max(1, end - start);
        const height = Math.max(6, Math.min(34, Math.round(6 + average * 150)));
        bar.style.height = `${height}px`;
    });
}

function renderResult(result) {
    if (!result) {
        updateResultVisibility(false);
        updateInputVisibility(false);
        return;
    }

    updateResultVisibility(true);
    updateInputVisibility(true);
    setText(elements.resultTitle, result.title || "Untitled Session");
    setHTMLContent(elements.summaryContent, result.summary || "");
    setText(elements.transcriptContent, result.transcript || "");
    setText(elements.inlineTranscriptContent, result.transcript || "");
    setHTMLContent(elements.actionItemsContent, result.action_items || "");
    setHTMLContent(elements.keyDecisionsContent, result.key_decisions || "");
    setHTMLContent(elements.openQuestionsContent, result.open_questions || "");

    // Reset transcript toggle to collapsed state on new result
    elements.inlineTranscript.classList.add("hidden");
    elements.transcriptToggleBtn.classList.remove("active");
    elements.transcriptToggleBtn.textContent = "Show Transcript";
}

function revealInputPanel() {
    elements.source.value = "";
    elements.mediaFile.value = "";
    elements.fileName.textContent = "No file selected";
    clearRecording();
    state.inputRevealed = true;
    setSourceMode("");
    updateInputVisibility(true, false);
    updateProcessingVisibility(false);
    elements.emptyState.scrollIntoView({ behavior: "smooth", block: "start" });
    elements.source.focus();
}

function closeResultModal() {
    elements.resultModal.classList.add("hidden");
    elements.resultModal.setAttribute("aria-hidden", "true");

    elements.resultNavButtons.forEach((button) => {
        button.classList.remove("active");
    });
}

function openResultModal(target) {
    elements.resultViews.forEach((view) => {
        const isActive = view.dataset.resultView === target;
        view.classList.toggle("active", isActive);
        if (isActive) {
            elements.resultModalTitle.textContent = view.dataset.resultTitle || "Meeting Detail";
        }
    });

    elements.resultNavButtons.forEach((button) => {
        button.classList.toggle("active", button.dataset.resultTarget === target);
    });

    elements.resultModal.classList.remove("hidden");
    elements.resultModal.setAttribute("aria-hidden", "false");
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
    updateProcessingVisibility(Boolean(data.processing));
    updateInputVisibility(Boolean(data.result), Boolean(data.processing));

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
    if (state.recording) {
        resetRecordingNodes();
    }

    if (state.recordingUrl) {
        URL.revokeObjectURL(state.recordingUrl);
    }

    state.recordedChunks = [];
    state.recordedFile = null;
    state.recordingUrl = "";
    elements.recordingPreview.removeAttribute("src");
    elements.recordingPreview.classList.add("hidden");
    setRecordingWaveVisible(false);
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
        setSourceMode("record");
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
        setRecordingWaveVisible(true);
        setProcessingUI(state.processing);

        processor.onaudioprocess = (event) => {
            if (!state.recording) {
                return;
            }

            const input = event.inputBuffer.getChannelData(0);
            state.recordedChunks.push(new Float32Array(input));
            updateRecordingWave(input);
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
    setRecordingWaveVisible(false);

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
        state.inputRevealed = false;
        updateResultVisibility(false);
        updateInputVisibility(false, true);
        updateProcessingVisibility(true);
        // Show "getting started" message; hide steps until real progress arrives
        elements.pipelineStarting.classList.remove("hidden");
        elements.pipelineSteps.classList.add("hidden");
        elements.pipelineSteps.innerHTML = "";
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
        setSourceMode("upload");
        clearRecording();
    }
    elements.fileName.textContent = file ? file.name : "No file selected";
});

elements.sourceModeButtons.forEach((button) => {
    button.addEventListener("click", () => {
        setSourceMode(button.dataset.sourceMode);
    });
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

    // Optimistically show user message right away
    elements.chatInput.value = "";
    elements.sendBtn.disabled = true;

    const currentHistory = [];
    elements.chatHistory.querySelectorAll(".chat-message").forEach((el) => {
        const role = el.classList.contains("user") ? "user" : "assistant";
        const content = el.querySelector(".chat-bubble")?.textContent || "";
        currentHistory.push({ role, content });
    });
    currentHistory.push({ role: "user", content: question });
    renderChat(currentHistory);

    setMessage("Fetching answer from the transcript context...", "info");

    try {
        const data = await postJSON("/api/chat", {
            question,
            tab_id: state.tabId,
            run_id: state.activeRunId,
        });
        renderChat(data.chat_history);
        setMessage("Answer generated from the current meeting transcript.", "info");
    } catch (error) {
        setMessage(error.message, "error");
    } finally {
        elements.sendBtn.disabled = false;
    }
});

elements.chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        elements.chatForm.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
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

elements.resultNavButtons.forEach((button) => {
    button.addEventListener("click", () => {
        openResultModal(button.dataset.resultTarget);
    });
});

elements.resultModalCloseButtons.forEach((button) => {
    button.addEventListener("click", closeResultModal);
});

elements.startNewBtn.addEventListener("click", revealInputPanel);

elements.transcriptToggleBtn.addEventListener("click", () => {
    const isHidden = elements.inlineTranscript.classList.contains("hidden");
    elements.inlineTranscript.classList.toggle("hidden");
    elements.transcriptToggleBtn.classList.toggle("active", isHidden);
    elements.transcriptToggleBtn.textContent = isHidden ? "Hide Transcript" : "Show Transcript";
});

window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !elements.resultModal.classList.contains("hidden")) {
        closeResultModal();
    }
});

window.addEventListener("load", async () => {
    setupRecordingWave();
    renderPipelineSteps({}, {});
    syncLanguageToggle(elements.language.value);
    try {
        await fetchState();
    } catch (error) {
        setMessage("Unable to load app state.", "error");
        setStatusChip("error", "Error");
    }
});

async function copyToClipboard(text, buttonEl) {
    try {
        await navigator.clipboard.writeText(text);
        
        const iconCopy = buttonEl.querySelector(".icon-copy");
        const iconCheck = buttonEl.querySelector(".icon-check");
        if (iconCopy && iconCheck) {
            iconCopy.classList.add("hidden");
            iconCheck.classList.remove("hidden");
            buttonEl.classList.add("copied");
            
            setTimeout(() => {
                iconCopy.classList.remove("hidden");
                iconCheck.classList.add("hidden");
                buttonEl.classList.remove("copied");
            }, 2000);
        }
    } catch (err) {
        console.error("Failed to copy text: ", err);
        setMessage("Failed to copy text to clipboard.", "error");
    }
}

function downloadAsPDF(type) {
    if (!window.jspdf) {
        setMessage("PDF library is not loaded yet. Please try again in a moment.", "error");
        return;
    }

    let titleText = "";
    let contentText = "";
    const sessionTitle = (elements.resultTitle ? elements.resultTitle.textContent : "Untitled Session") || "Untitled Session";

    if (type === "summary") {
        titleText = `Summary - ${sessionTitle}`;
        contentText = elements.summaryContent ? elements.summaryContent.textContent : "";
    } else if (type === "transcript") {
        titleText = `Transcript - ${sessionTitle}`;
        contentText = elements.inlineTranscriptContent ? elements.inlineTranscriptContent.textContent : "";
    }

    if (!contentText) {
        setMessage("No content to export.", "error");
        return;
    }

    const { jsPDF } = window.jspdf;
    const doc = new jsPDF();

    doc.setFont("helvetica", "bold");
    doc.setFontSize(16);
    doc.setTextColor(16, 163, 127);
    doc.text(titleText, 14, 22);

    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.setTextColor(120);
    const dateStr = new Date().toLocaleString();
    doc.text(`AI Video Assistant | Exported on ${dateStr}`, 14, 28);
    doc.line(14, 32, 196, 32);

    doc.setFont("helvetica", "normal");
    doc.setFontSize(10.5);
    doc.setTextColor(40);

    const splitText = doc.splitTextToSize(contentText, 180);
    let y = 40;
    const pageHeight = doc.internal.pageSize.height;

    for (let i = 0; i < splitText.length; i++) {
        if (y > pageHeight - 20) {
            doc.addPage();
            y = 20;
        }
        doc.text(splitText[i], 14, y);
        y += 6.5;
    }

    const filename = `${type}_${sessionTitle.toLowerCase().replace(/[^a-z0-9]+/g, "_")}.pdf`;
    doc.save(filename);
    setMessage(`${type.charAt(0).toUpperCase() + type.slice(1)} PDF downloaded successfully.`, "info");
}

// Attach Copy and PDF handlers
document.addEventListener("click", (event) => {
    const copyBtn = event.target.closest(".copy-btn");
    if (copyBtn) {
        if (copyBtn.id === "modal-copy-btn") {
            const activeView = document.querySelector(".result-view.active");
            if (activeView) {
                const textBlock = activeView.querySelector(".text-block");
                if (textBlock) {
                    copyToClipboard(textBlock.textContent || textBlock.innerText, copyBtn);
                }
            }
        } else {
            const targetId = copyBtn.getAttribute("data-copy-target");
            if (targetId) {
                const targetEl = document.getElementById(targetId);
                if (targetEl) {
                    copyToClipboard(targetEl.textContent || targetEl.innerText, copyBtn);
                }
            }
        }
        return;
    }

    const pdfBtn = event.target.closest(".pdf-btn");
    if (pdfBtn) {
        const type = pdfBtn.getAttribute("data-pdf-type");
        if (type) {
            downloadAsPDF(type);
        }
    }
});
