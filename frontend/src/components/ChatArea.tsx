import React, { useEffect, useRef } from 'react';
import { useChat } from '../context/ChatContext';
import ChatMessage from './ChatMessage';
import ChatInput from './ChatInput';

const containerStyle: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
  backgroundColor: '#f9fbfa',
};

const messagesContainerStyle: React.CSSProperties = {
  flex: 1,
  overflowY: 'auto',
  padding: '24px 24px 16px',
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
};

const emptyStateStyle: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 16,
  color: '#5c6c75',
  textAlign: 'center',
  padding: 40,
};

const emptyIconStyle: React.CSSProperties = {
  width: 64,
  height: 64,
  borderRadius: '50%',
  backgroundColor: '#E3FCF7',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
};

const suggestionsStyle: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 8,
  justifyContent: 'center',
  marginTop: 8,
  maxWidth: 720,
};

const suggestionChipStyle: React.CSSProperties = {
  padding: '8px 16px',
  backgroundColor: '#FFFFFF',
  border: '1px solid #e8edeb',
  borderRadius: 20,
  fontSize: 13,
  color: '#001E2B',
  cursor: 'pointer',
  transition: 'all 0.15s ease',
  fontFamily: 'inherit',
};

// Per-domain starter prompts. Each is grounded in the actual seeded data so
// clicking them surfaces real answers (KB hits + operational rows + planner
// todos), not generic LLM boilerplate. These exercise the planner by asking
// for multi-step work so the Plan drawer populates visibly.
const SUGGESTIONS: Record<string, string[]> = {
  reference: [
    'Plan and run a short research report on Atlas Vector Search, citing KB sources.',
    'Draft a customer-tier breakdown from the customers collection and save it to a file.',
    'List all orders with their status and amount.',
  ],
  healthcare: [
    "Plan a case summary for patient pt_H001: pull encounters, meds, and relevant policy, then draft a note.",
    'Research the HA-CDI infection-control policy and produce an operator-ready briefing.',
    'List every encounter for patient pt_H001 with dates and primary diagnosis.',
  ],
  finance: [
    'Plan a dispute workup for the unauthorized CARD_DEBIT on checking account acct_F1001: pull the transaction + Reg E policy + draft a response.',
    'Research overdraft-fee policy on consumer checking accounts and save the writeup to a file.',
    'List all CARD_DEBIT transactions on account acct_F1001 with amounts and dates.',
  ],
  telco: [
    'Plan a tier-2 triage note for the P1 tower-A114 outage: pull the ticket, the MTTR targets, and draft a customer-ready status update.',
    'Compare the Gold Unlimited and Silver 30GB rate plans and save the comparison.',
    'Research SLA-credit eligibility for the P2 sim-swap case on subscriber sub_T004 and draft a summary.',
  ],
  retail: [
    'Plan a returns-audit for customer cust_R001: pull their orders, cross-check against the returns policy, and draft an exception report.',
    'Research promotion-stacking rules on coupons and save the explainer to a file.',
    'List all delivered orders with customer_id and total.',
  ],
};

export default function ChatArea() {
  const { messages, isLoading, domain, sendMessage } = useChat();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  const suggestions = (domain && SUGGESTIONS[domain]) || [];

  return (
    <div style={containerStyle}>
      <div style={messagesContainerStyle} ref={scrollRef}>
        {messages.length === 0 ? (
          <div style={emptyStateStyle}>
            <div style={emptyIconStyle}>
              <svg
                width="32"
                height="32"
                viewBox="0 0 120 278"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  d="M82.3229 28.6444C71.5367 15.8469 62.2485 2.84945 60.351 0.149971C60.1512 -0.0499903 59.8515 -0.0499903 59.6518 0.149971C57.7542 2.84945 48.4661 15.8469 37.6798 28.6444C-54.9019 146.721 52.2613 226.406 52.2613 226.406L53.1601 227.006C53.959 239.303 55.9565 257 55.9565 257H59.9514H63.9463C63.9463 257 65.9438 239.403 66.7428 227.006L67.6416 226.306C67.7414 226.406 174.905 146.721 82.3229 28.6444ZM59.9514 224.606C59.9514 224.606 55.1576 220.507 53.8592 218.408V218.207L59.6518 89.6326C59.6518 89.2326 60.2511 89.2326 60.2511 89.6326L66.0436 218.207V218.408C64.7453 220.507 59.9514 224.606 59.9514 224.606Z"
                  fill="#00684A"
                />
              </svg>
            </div>
            <div>
              <h3 style={{ fontSize: 18, fontWeight: 600, color: '#001E2B', marginBottom: 6 }}>
                {domain ? `${domain.charAt(0).toUpperCase() + domain.slice(1)} pack` : 'Select a domain pack'}
              </h3>
              <p style={{ fontSize: 14, color: '#5c6c75', maxWidth: 520 }}>
                {domain
                  ? 'Ask a question grounded in the active domain pack. The agent routes to reasoning, data, search, or writing specialists as needed.'
                  : 'Choose a domain pack from the sidebar to start.'}
              </p>
            </div>
            {suggestions.length > 0 && (
              <div style={suggestionsStyle}>
                {suggestions.map((s) => (
                  <button
                    key={s}
                    style={suggestionChipStyle}
                    onClick={() => sendMessage(s)}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.borderColor = '#00684A';
                      (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#E3FCF7';
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLButtonElement).style.borderColor = '#e8edeb';
                      (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#FFFFFF';
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          messages.map((msg) => <ChatMessage key={msg.id} message={msg} />)
        )}
      </div>
      <ChatInput />
    </div>
  );
}
