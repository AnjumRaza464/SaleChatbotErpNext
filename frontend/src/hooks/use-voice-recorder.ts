"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";

export type VoiceState = "idle" | "recording" | "transcribing";

/** Recordings stop automatically after this long. */
const MAX_SECONDS = 120;

// Chrome/Edge/Firefox record webm/ogg; Safari records mp4.
const FORMATS = [
  { mime: "audio/webm", ext: "webm" },
  { mime: "audio/ogg", ext: "ogg" },
  { mime: "audio/mp4", ext: "mp4" },
];

function pickFormat() {
  return FORMATS.find((f) => MediaRecorder.isTypeSupported(f.mime)) ?? FORMATS[0];
}

/**
 * Records from the microphone and transcribes the clip on the backend.
 * `onText` receives the transcript once it is ready.
 */
export function useVoiceRecorder(onText: (text: string) => void) {
  const [state, setState] = useState<VoiceState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const onTextRef = useRef(onText);
  useEffect(() => {
    onTextRef.current = onText;
  }, [onText]);

  const supported = typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

  const clearTimer = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  };

  const stop = useCallback(() => {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }, []);

  const start = useCallback(async () => {
    setError(null);
    if (!supported) {
      setError("Voice input needs a modern browser on localhost or HTTPS.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      const name = (e as DOMException).name;
      setError(name === "NotAllowedError" ? "Microphone access was blocked. Allow it in the browser's address bar." : "No microphone found.");
      return;
    }

    const format = pickFormat();
    const rec = new MediaRecorder(stream, { mimeType: format.mime });
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
    rec.onstop = async () => {
      clearTimer();
      stream.getTracks().forEach((t) => t.stop());
      recorder.current = null;
      const blob = new Blob(chunks, { type: format.mime });
      if (blob.size === 0) {
        setState("idle");
        return;
      }
      setState("transcribing");
      try {
        const { text } = await api.transcribe(blob, `voice.${format.ext}`);
        onTextRef.current(text);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setState("idle");
      }
    };

    recorder.current = rec;
    rec.start();
    setSeconds(0);
    setState("recording");
    const startedAt = Date.now();
    timer.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      setSeconds(elapsed);
      if (elapsed >= MAX_SECONDS && rec.state === "recording") rec.stop();
    }, 1000);
  }, [supported]);

  // Release the microphone if the component unmounts mid-recording.
  useEffect(
    () => () => {
      clearTimer();
      const rec = recorder.current;
      if (rec) {
        rec.onstop = null;
        if (rec.state === "recording") rec.stop();
        rec.stream.getTracks().forEach((t) => t.stop());
      }
    },
    [],
  );

  return { state, seconds, error, clearError: () => setError(null), start, stop };
}
