import { useEffect, useRef, useState } from 'react';
import { getSpeechAuthorization } from '../../services/speechApi.js';

export default function ChatInput({
  onSend,
  disabled,
  inputRef: suppliedInputRef,
  clearToken,
  speechHints = [],
  placeholder = 'Escribe tu consulta sobre devoluciones...',
}) {
  const localInputRef = useRef(null);
  const inputRef = suppliedInputRef ?? localInputRef;
  const recognizerRef = useRef(null);
  const mountedRef = useRef(false);
  const disabledRef = useRef(disabled);
  const speechStatusRef = useRef('idle');
  const voiceSendPendingRef = useRef(false);
  const [speechStatus, setSpeechStatus] = useState('idle');
  const [interimTranscript, setInterimTranscript] = useState('');
  const [speechError, setSpeechError] = useState('');
  disabledRef.current = disabled;

  function updateSpeechStatus(status) {
    speechStatusRef.current = status;
    if (mountedRef.current) setSpeechStatus(status);
  }

  function closeRecognizer(recognizer) {
    if (recognizerRef.current !== recognizer) return;
    recognizerRef.current = null;
    recognizer.close();
    if (speechStatusRef.current !== 'sending') updateSpeechStatus('idle');
    if (mountedRef.current) setInterimTranscript('');
  }

  function stopSpeechRecognition(nextStatus = 'idle') {
    const recognizer = recognizerRef.current;
    updateSpeechStatus(nextStatus);
    if (mountedRef.current) setInterimTranscript('');
    if (!recognizer) return;

    recognizer.stopContinuousRecognitionAsync(
      () => closeRecognizer(recognizer),
      () => {
        closeRecognizer(recognizer);
        if (mountedRef.current) {
          setSpeechError('No se pudo detener el dictado correctamente. Puedes continuar escribiendo.');
        }
      },
    );
  }

  function appendRecognizedText(text) {
    const input = inputRef.current;
    const recognizedText = text.trim();
    if (!input || !recognizedText) return '';

    const existingText = input.value;
    const separator = existingText && !/\s$/.test(existingText) ? ' ' : '';
    const nextText = `${existingText}${separator}${recognizedText}`;
    input.value = nextText.slice(0, 2000);
    input.setSelectionRange(input.value.length, input.value.length);
    input.dispatchEvent(new Event('input', { bubbles: true }));

    if (nextText.length > 2000 && mountedRef.current) {
      setSpeechError('Se alcanzó el límite de texto. Revisa la transcripción antes de continuar.');
    }
    return input.value;
  }

  async function sendRecognizedCommand() {
    const input = inputRef.current;
    const commandPattern = /\s*(?:enviar|env[ií]a|manda(?:r|me)?|mándame)\s+(?:(?:este|el)\s+)?mensaje[.!?,;:…]*$/i;
    const commandMatch = input?.value.match(commandPattern);
    if (!input || !commandMatch) return;
    if (voiceSendPendingRef.current) return;

    voiceSendPendingRef.current = true;
    stopSpeechRecognition('sending');
    const message = input.value.slice(0, commandMatch.index).trim();

    if (!message) {
      setSpeechError('No hay texto para enviar. Dicta tu consulta y di “Enviar mensaje”.');
      voiceSendPendingRef.current = false;
      updateSpeechStatus('idle');
      return;
    }

    input.value = message;
    input.setSelectionRange(input.value.length, input.value.length);
    input.dispatchEvent(new Event('input', { bubbles: true }));

    try {
      const sent = await onSend(message);
      if (sent && inputRef.current) {
        inputRef.current.value = '';
        inputRef.current.style.height = 'auto';
        inputRef.current.dispatchEvent(new Event('input', { bubbles: true }));
      }
    } finally {
      voiceSendPendingRef.current = false;
      updateSpeechStatus('idle');
    }
  }

  async function startSpeechRecognition() {
    if (disabledRef.current || speechStatusRef.current !== 'idle') return;
    setSpeechError('');
    updateSpeechStatus('starting');

    let recognizer;
    try {
      const { token, region } = await getSpeechAuthorization();
      if (!mountedRef.current || disabledRef.current) {
        updateSpeechStatus('idle');
        return;
      }

      const speechSdk = await import('microsoft-cognitiveservices-speech-sdk');
      if (!mountedRef.current || disabledRef.current) {
        updateSpeechStatus('idle');
        return;
      }

      const speechConfig = speechSdk.SpeechConfig.fromAuthorizationToken(token, region);
      speechConfig.speechRecognitionLanguage = 'es-MX';
      const audioConfig = speechSdk.AudioConfig.fromDefaultMicrophoneInput();
      recognizer = new speechSdk.SpeechRecognizer(speechConfig, audioConfig);
      if (speechHints.length > 0) {
        const phraseList = speechSdk.PhraseListGrammar.fromRecognizer(recognizer);
        [...new Set(speechHints.filter((hint) => typeof hint === 'string').map((hint) => hint.trim()).filter(Boolean))]
          .slice(0, 100)
          .forEach((hint) => phraseList.addPhrase(hint));
      }
      recognizerRef.current = recognizer;
      recognizer.recognizing = (_, event) => {
        if (
          mountedRef.current
          && event.result.reason === speechSdk.ResultReason.RecognizingSpeech
        ) {
          setInterimTranscript(event.result.text);
        }
      };
      recognizer.recognized = (_, event) => {
        if (mountedRef.current) setInterimTranscript('');
        if (
          event.result.reason === speechSdk.ResultReason.RecognizedSpeech
          && !voiceSendPendingRef.current
        ) {
          appendRecognizedText(event.result.text);
          void sendRecognizedCommand();
        }
      };
      recognizer.canceled = (_, event) => {
        if (event.reason === speechSdk.CancellationReason.Error && mountedRef.current) {
          setSpeechError('Azure Speech interrumpió el dictado. Revisa la conexión y vuelve a intentarlo.');
        }
        closeRecognizer(recognizer);
      };
      recognizer.sessionStopped = () => closeRecognizer(recognizer);
      recognizer.startContinuousRecognitionAsync(
        () => {
          if (mountedRef.current && recognizerRef.current === recognizer) {
            updateSpeechStatus('listening');
          }
        },
        () => {
          closeRecognizer(recognizer);
          if (mountedRef.current) {
            setSpeechError('No se pudo iniciar el micrófono. Verifica el permiso del navegador e inténtalo de nuevo.');
          }
        },
      );
    } catch (error) {
      if (recognizer) closeRecognizer(recognizer);
      else updateSpeechStatus('idle');
      if (mountedRef.current) {
        setSpeechError(error instanceof Error ? error.message : 'No se pudo iniciar el dictado de voz.');
      }
    }
  }

  useEffect(() => {
    if (clearToken === undefined) return;
    stopSpeechRecognition();
    const input = inputRef.current;
    if (!input) return;
    input.value = '';
    input.style.height = 'auto';
  }, [clearToken, inputRef]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const recognizer = recognizerRef.current;
      recognizerRef.current = null;
      if (recognizer) {
        recognizer.stopContinuousRecognitionAsync(
          () => recognizer.close(),
          () => recognizer.close(),
        );
      }
    };
  }, []);

  useEffect(() => {
    if (disabled && recognizerRef.current) stopSpeechRecognition();
  }, [disabled]);

  async function submitMessage(event) {
    event.preventDefault();
    const value = inputRef.current?.value.trim();
    if (!value || disabled || speechStatusRef.current !== 'idle') return;
    const sent = await onSend(value);
    if (sent) {
      inputRef.current.value = '';
      inputRef.current.style.height = 'auto';
    }
  }

  function resizeInput() {
    const input = inputRef.current;
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 144)}px`;
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form.requestSubmit();
    }
  }

  function toggleSpeechRecognition() {
    if (speechStatus === 'listening') stopSpeechRecognition();
    else startSpeechRecognition();
  }

  return (
    <div className="chat-input-area">
      <form className="chat-input-form" onSubmit={submitMessage}>
        <label className="visually-hidden" htmlFor="chat-message">Escribe tu consulta</label>
        <textarea
          id="chat-message"
          ref={inputRef}
          rows="1"
          maxLength={2000}
          placeholder={placeholder}
          onInput={resizeInput}
          onKeyDown={handleKeyDown}
          disabled={disabled}
        />
        <button
          className={`speech-button${speechStatus === 'listening' ? ' is-listening' : ''}`}
          type="button"
          onClick={toggleSpeechRecognition}
          disabled={disabled || speechStatus === 'starting'}
          aria-label={speechStatus === 'listening' ? 'Detener dictado' : 'Dictar consulta por voz'}
          aria-pressed={speechStatus === 'listening'}
          title={speechStatus === 'listening' ? 'Detener dictado' : 'Dictar consulta por voz'}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z" />
            <path d="M19 11a7 7 0 0 1-14 0m7 7v3m-4 0h8" />
          </svg>
          <span>
            {speechStatus === 'starting' ? 'Conectando' : speechStatus === 'listening' ? 'Detener' : 'Dictar'}
          </span>
        </button>
        <button
          className="send-button"
          type="submit"
          disabled={disabled || speechStatus !== 'idle'}
          aria-label="Enviar consulta"
          title="Enviar consulta"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 12 20 4l-5 16-3-6-8-2Zm8 2 4-5" />
          </svg>
        </button>
      </form>
      <p className="speech-command-hint">
        Al dictar, di «Enviar mensaje» para enviar tu mensaje de voz.
      </p>
      <p className="keyboard-hint">Enter envía · Shift+Enter agrega una línea</p>
      <p className="speech-privacy-note">
        Al dictar, el audio se procesa con Azure Speech. Revisa el texto transcrito antes de enviarlo.
      </p>
      {speechStatus === 'starting' && <p className="speech-status" role="status">Conectando con Azure Speech…</p>}
      {speechStatus === 'listening' && (
        <p className="speech-status" role="status">Dictado activo.</p>
      )}
      {interimTranscript && (
        <p className="speech-interim" aria-live="off">
          <strong>Transcripción en vivo:</strong> {interimTranscript}
        </p>
      )}
      {speechError && <p className="speech-error" role="alert">{speechError}</p>}
    </div>
  );
}