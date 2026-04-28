import React, { useEffect, useState } from 'react';
import { fetchHealth } from '../api/client';

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  height: 64,
  padding: '0 24px',
  backgroundColor: '#001E2B',
  color: '#FFFFFF',
  flexShrink: 0,
};

const logoContainerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
};

const titleStyle: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 600,
  letterSpacing: '-0.02em',
};

const subtitleStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 400,
  color: '#00ED64',
  marginLeft: 8,
};

const modelBadgeStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '6px 12px',
  backgroundColor: '#0c2d3f',
  border: '1px solid #1c3d4f',
  borderRadius: 20,
  fontSize: 12,
  color: '#C1D0D5',
  cursor: 'not-allowed',
  userSelect: 'none',
};

/**
 * Model badge: display-only. Reads `llm_model` from GET /api/health on mount
 * so the label stays aligned with backend env LLM_MODEL without the UI
 * ever offering a selector.
 */
function ModelBadge() {
  const [label, setLabel] = useState<string>('Bedrock Claude Sonnet');
  useEffect(() => {
    let cancelled = false;
    fetchHealth()
      .then((h) => {
        if (cancelled) return;
        if (h.llm_model) setLabel(h.llm_model);
      })
      .catch(() => {
        /* health fetch is best-effort; keep the default label */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return (
    <div
      style={modelBadgeStyle}
      title="Model is fixed in this demo; change LLM via backend env LLM_MODEL."
    >
      <svg width="10" height="10" viewBox="0 0 16 16" fill="#00ED64">
        <circle cx="8" cy="8" r="4" />
      </svg>
      {label}
    </div>
  );
}

export default function Header() {
  return (
    <header style={headerStyle}>
      <div style={logoContainerStyle}>
        <svg
          width="28"
          height="28"
          viewBox="0 0 120 278"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M82.3229 28.6444C71.5367 15.8469 62.2485 2.84945 60.351 0.149971C60.1512 -0.0499903 59.8515 -0.0499903 59.6518 0.149971C57.7542 2.84945 48.4661 15.8469 37.6798 28.6444C-54.9019 146.721 52.2613 226.406 52.2613 226.406L53.1601 227.006C53.959 239.303 55.9565 257 55.9565 257H59.9514H63.9463C63.9463 257 65.9438 239.403 66.7428 227.006L67.6416 226.306C67.7414 226.406 174.905 146.721 82.3229 28.6444ZM59.9514 224.606C59.9514 224.606 55.1576 220.507 53.8592 218.408V218.207L59.6518 89.6326C59.6518 89.2326 60.2511 89.2326 60.2511 89.6326L66.0436 218.207V218.408C64.7453 220.507 59.9514 224.606 59.9514 224.606Z"
            fill="#00ED64"
          />
        </svg>
        <span style={titleStyle}>MongoDB Deep Agents</span>
        <span style={subtitleStyle}>Planner + Researcher Subagent on MongoDB Atlas</span>
      </div>
      <ModelBadge />
    </header>
  );
}
