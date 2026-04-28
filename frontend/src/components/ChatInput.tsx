import React, { useEffect, useRef, useState } from 'react';
import { useChat } from '../context/ChatContext';

const containerStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  padding: '0 24px 20px',
  backgroundColor: '#FFFFFF',
  borderTop: '1px solid #e8edeb',
};

const inputRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-end',
  gap: 10,
  paddingTop: 16,
};

const textareaStyle: React.CSSProperties = {
  flex: 1,
  padding: '12px 16px',
  border: '2px solid #e8edeb',
  borderRadius: 10,
  fontSize: 14,
  fontFamily: 'inherit',
  lineHeight: 1.5,
  resize: 'none',
  outline: 'none',
  maxHeight: 150,
  minHeight: 44,
  color: '#001E2B',
  transition: 'border-color 0.15s ease',
};

const buttonStyle: React.CSSProperties = {
  padding: '12px 20px',
  backgroundColor: '#00684A',
  color: '#FFFFFF',
  border: 'none',
  borderRadius: 10,
  fontSize: 14,
  fontWeight: 600,
  fontFamily: 'inherit',
  cursor: 'pointer',
  transition: 'background-color 0.15s ease',
  flexShrink: 0,
  height: 44,
};

const disabledButtonStyle: React.CSSProperties = {
  ...buttonStyle,
  backgroundColor: '#889397',
  cursor: 'not-allowed',
};

const hintStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#991b1b',
  marginTop: 6,
};

export default function ChatInput() {
  const { sendMessage, isLoading, domain, userId } = useChat();
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 150) + 'px';
    }
  }, [input]);

  const handleSubmit = () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading || !domain || !userId) return;
    setInput('');
    sendMessage(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const canSend = !!input.trim() && !isLoading && !!domain && !!userId;
  const placeholder = !domain
    ? 'Select a domain first'
    : !userId
    ? 'Enter a user id to start'
    : `Ask about ${domain}...`;

  return (
    <div style={containerStyle}>
      <div style={inputRowStyle}>
        <textarea
          ref={textareaRef}
          style={{
            ...textareaStyle,
            borderColor: !domain || !userId ? '#fca5a5' : '#e8edeb',
          }}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isLoading || !domain || !userId}
          rows={1}
          onFocus={(e) => {
            e.currentTarget.style.borderColor = '#00684A';
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderColor = !domain || !userId ? '#fca5a5' : '#e8edeb';
          }}
        />
        <button
          style={canSend ? buttonStyle : disabledButtonStyle}
          onClick={handleSubmit}
          disabled={!canSend}
          onMouseEnter={(e) => {
            if (canSend)
              (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#008558';
          }}
          onMouseLeave={(e) => {
            if (canSend)
              (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#00684A';
          }}
        >
          {isLoading ? 'Streaming…' : 'Send'}
        </button>
      </div>
      {!userId && <div style={hintStyle}>Enter a user id in the sidebar to start.</div>}
    </div>
  );
}
