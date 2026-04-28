import React, { useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '../context/ChatContext';

interface Props {
  message: Message;
}

const userBubbleStyle: React.CSSProperties = {
  maxWidth: '75%',
  padding: '12px 16px',
  borderRadius: '16px 16px 4px 16px',
  backgroundColor: '#00684A',
  color: '#FFFFFF',
  fontSize: 14,
  lineHeight: 1.6,
  alignSelf: 'flex-end',
  wordBreak: 'break-word',
};

const assistantBubbleStyle: React.CSSProperties = {
  maxWidth: '85%',
  padding: '16px 20px',
  borderRadius: '16px 16px 16px 4px',
  backgroundColor: '#FFFFFF',
  color: '#001E2B',
  fontSize: 14,
  lineHeight: 1.7,
  alignSelf: 'flex-start',
  border: '1px solid #e8edeb',
  boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
  wordBreak: 'break-word',
};

const errorBubbleStyle: React.CSSProperties = {
  ...assistantBubbleStyle,
  backgroundColor: '#fef2f2',
  border: '1px solid #fecaca',
  color: '#991b1b',
};

const roleTagStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  textTransform: 'uppercase' as const,
  letterSpacing: '0.05em',
  marginBottom: 6,
  color: '#889397',
};

const markdownStyle = `
.chat-markdown pre {
  background: #0c2d3f;
  color: #e0f0e8;
  padding: 14px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 10px 0;
  font-size: 13px;
  line-height: 1.5;
}
.chat-markdown code {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 13px;
}
.chat-markdown :not(pre) > code {
  background: #E3FCF7;
  color: #00684A;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.chat-markdown p { margin: 6px 0; }
.chat-markdown ul, .chat-markdown ol { margin: 6px 0; padding-left: 20px; }
.chat-markdown li { margin: 3px 0; }
.chat-markdown h1, .chat-markdown h2, .chat-markdown h3 {
  margin: 12px 0 6px;
  color: #001E2B;
}
.chat-markdown table {
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 13px;
}
.chat-markdown th, .chat-markdown td {
  border: 1px solid #e8edeb;
  padding: 6px 10px;
  text-align: left;
}
.chat-markdown th { background: #f3f5f4; font-weight: 600; }
.chat-markdown blockquote {
  border-left: 3px solid #00ED64;
  padding-left: 12px;
  margin: 8px 0;
  color: #5c6c75;
}
.chat-markdown a { color: #00684A; text-decoration: none; }
.chat-markdown a:hover { text-decoration: underline; }
`;

const ChatMessage: React.FC<Props> = React.memo(({ message }) => {
  const isUser = message.role === 'user';
  const isError = message.role === 'error';

  const bubbleStyle = isError
    ? errorBubbleStyle
    : isUser
    ? userBubbleStyle
    : assistantBubbleStyle;

  const renderCode = useCallback(
    (props: { className?: string; children?: React.ReactNode }) => {
      const { className, children } = props;
      return <code className={className}>{children}</code>;
    },
    [],
  );

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
        padding: '4px 0',
      }}
    >
      {!isUser && <div style={roleTagStyle}>{isError ? 'Error' : 'Assistant'}</div>}
      <div style={bubbleStyle}>
        {isUser ? (
          <div>{message.content}</div>
        ) : (
          <>
            <style>{markdownStyle}</style>
            <div className="chat-markdown">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{ code: renderCode }}
              >
                {message.content || (isError ? '' : '…')}
              </ReactMarkdown>
            </div>
          </>
        )}
      </div>
    </div>
  );
});

ChatMessage.displayName = 'ChatMessage';
export default ChatMessage;
