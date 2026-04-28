import React, { useState } from 'react';
import { useChat } from '../context/ChatContext';
import type { Todo } from '../api/client';

/**
 * Collapsible right-hand drawer showing the deep-agent planner's todos
 * for the active `(user_id, thread_id)`. Populated after every `done` SSE
 * frame via `GET /api/plans`. The deep-agent differentiator versus the
 * sibling agentic-ai UI — the todo list is what makes the "planner" pattern
 * visible to demo watchers.
 */

const containerStyle: React.CSSProperties = {
  width: 320,
  flexShrink: 0,
  display: 'flex',
  flexDirection: 'column',
  backgroundColor: '#FFFFFF',
  borderLeft: '1px solid #e8edeb',
  overflow: 'hidden',
  transition: 'width 0.18s ease',
};

const collapsedStyle: React.CSSProperties = {
  ...containerStyle,
  width: 48,
};

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '14px 16px',
  borderBottom: '1px solid #e8edeb',
  fontSize: 13,
  fontWeight: 600,
  color: '#001E2B',
  cursor: 'pointer',
  userSelect: 'none',
  backgroundColor: '#f9fbfa',
};

const collapsedHeaderStyle: React.CSSProperties = {
  ...headerStyle,
  justifyContent: 'center',
  writingMode: 'vertical-rl',
  padding: '14px 0',
  borderBottom: 'none',
  borderRight: '1px solid #e8edeb',
  height: '100%',
};

const listStyle: React.CSSProperties = {
  flex: 1,
  overflowY: 'auto',
  padding: '12px 16px',
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
};

const rowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 10,
  fontSize: 13,
  lineHeight: 1.5,
  padding: '8px 10px',
  borderRadius: 6,
  backgroundColor: '#f9fbfa',
  border: '1px solid #e8edeb',
  color: '#001E2B',
};

const glyphStyle: React.CSSProperties = {
  flexShrink: 0,
  width: 18,
  textAlign: 'center',
  fontSize: 14,
  lineHeight: '22px',
};

const emptyStyle: React.CSSProperties = {
  padding: '20px 16px',
  color: '#889397',
  fontSize: 12,
  fontStyle: 'italic',
  textAlign: 'center',
};

function glyphFor(status: Todo['status']): { char: string; color: string } {
  switch (status) {
    case 'completed':
      return { char: '✓', color: '#00ED64' };
    case 'in_progress':
      return { char: '●', color: '#00684A' };
    default:
      return { char: '○', color: '#889397' };
  }
}

export default function PlanDrawer() {
  const { plan } = useChat();
  const [collapsed, setCollapsed] = useState(true);

  if (collapsed) {
    return (
      <aside style={collapsedStyle}>
        <div
          style={collapsedHeaderStyle}
          onClick={() => setCollapsed(false)}
          title="Show plan"
        >
          Plan ({plan.todos.length})
        </div>
      </aside>
    );
  }

  return (
    <aside style={containerStyle}>
      <div style={headerStyle} onClick={() => setCollapsed(true)} title="Hide plan">
        <span>Plan ({plan.todos.length})</span>
        <span style={{ color: '#889397', fontWeight: 400 }}>▸</span>
      </div>
      {plan.todos.length === 0 ? (
        <div style={emptyStyle}>No plan yet — send a message to populate.</div>
      ) : (
        <div style={listStyle}>
          {plan.todos.map((t) => {
            const g = glyphFor(t.status);
            return (
              <div key={t.id} style={rowStyle}>
                <span style={{ ...glyphStyle, color: g.color }}>{g.char}</span>
                <span>{t.text}</span>
              </div>
            );
          })}
        </div>
      )}
    </aside>
  );
}
