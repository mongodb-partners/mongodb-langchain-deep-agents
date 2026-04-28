import React from 'react';
import { useChat } from '../context/ChatContext';

const sidebarStyle: React.CSSProperties = {
  width: 300,
  backgroundColor: '#001E2B',
  color: '#FFFFFF',
  display: 'flex',
  flexDirection: 'column',
  flexShrink: 0,
  overflow: 'hidden',
};

const sectionStyle: React.CSSProperties = {
  padding: '20px 16px',
  borderBottom: '1px solid #1c2d38',
};

const sectionTitleStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  textTransform: 'uppercase' as const,
  letterSpacing: '0.08em',
  color: '#889397',
  marginBottom: 10,
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  backgroundColor: '#0c2d3f',
  border: '1px solid #1c3d4f',
  borderRadius: 6,
  color: '#FFFFFF',
  fontSize: 14,
  fontFamily: 'inherit',
  outline: 'none',
};

const packItemStyle: React.CSSProperties = {
  padding: '10px 12px',
  borderRadius: 6,
  cursor: 'pointer',
  fontSize: 13,
  transition: 'background-color 0.15s ease',
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  wordBreak: 'break-word' as const,
};

const packListStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  flex: 1,
  overflowY: 'auto',
  padding: '12px 16px',
};

const buttonStyle: React.CSSProperties = {
  width: '100%',
  padding: '10px 16px',
  backgroundColor: '#00684A',
  color: '#FFFFFF',
  border: 'none',
  borderRadius: 6,
  fontSize: 13,
  fontWeight: 500,
  fontFamily: 'inherit',
  cursor: 'pointer',
  transition: 'background-color 0.15s ease',
};

const errorStyle: React.CSSProperties = {
  padding: '8px 12px',
  backgroundColor: 'rgba(207, 74, 74, 0.15)',
  border: '1px solid rgba(207, 74, 74, 0.3)',
  borderRadius: 6,
  color: '#ff8080',
  fontSize: 12,
};

export default function Sidebar() {
  const {
    domain,
    setDomain,
    userId,
    setUserId,
    domains,
    domainsError,
    newConversation,
  } = useChat();

  return (
    <aside style={sidebarStyle}>
      <div style={sectionStyle}>
        <div style={sectionTitleStyle}>User ID</div>
        <input
          style={inputStyle}
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          placeholder="alice"
        />
        <div
          style={{
            fontSize: 11,
            color: '#889397',
            marginTop: 6,
          }}
        >
          Scopes memory + chat history per user.
        </div>
      </div>

      <div style={{ ...sectionStyle, borderBottom: 'none', paddingBottom: 8 }}>
        <div style={sectionTitleStyle}>Domain Pack</div>
        {domainsError && <div style={errorStyle}>{domainsError}</div>}
        {!domainsError && domains.length === 0 && (
          <div style={{ color: '#889397', fontSize: 13, padding: '8px 0' }}>
            Loading domains...
          </div>
        )}
      </div>

      <div style={packListStyle}>
        {domains.map((d) => {
          const active = d.name === domain;
          return (
            <div
              key={d.name}
              style={{
                ...packItemStyle,
                backgroundColor: active ? '#0c3d2f' : 'transparent',
                color: active ? '#00ED64' : '#C1D0D5',
                border: active ? '1px solid #00684A' : '1px solid transparent',
              }}
              onClick={() => {
                if (!active) setDomain(d.name);
              }}
              onMouseEnter={(e) => {
                if (!active)
                  (e.currentTarget as HTMLDivElement).style.backgroundColor = '#0c2d3f';
              }}
              onMouseLeave={(e) => {
                if (!active)
                  (e.currentTarget as HTMLDivElement).style.backgroundColor = 'transparent';
              }}
            >
              <span style={{ fontWeight: 600 }}>{d.name}</span>
              <span style={{ fontSize: 11, color: active ? '#A5E9C4' : '#889397' }}>
                {d.description}
              </span>
            </div>
          );
        })}
      </div>

      <div style={{ padding: '12px 16px', borderTop: '1px solid #1c2d38' }}>
        <button
          style={buttonStyle}
          onClick={newConversation}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#008558';
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#00684A';
          }}
        >
          New Conversation
        </button>
      </div>
    </aside>
  );
}
