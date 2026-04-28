import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
} from 'react';
import {
  streamChat,
  fetchDomains,
  fetchPlan,
  type Domain,
  type PlanSnapshot,
} from '../api/client';

function genId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  timestamp: Date;
}

interface ChatContextValue {
  messages: Message[];
  isLoading: boolean;
  domain: string;
  userId: string;
  domains: Domain[];
  domainsError: string;
  plan: PlanSnapshot;
  setDomain: (d: string) => void;
  setUserId: (u: string) => void;
  sendMessage: (message: string) => void;
  newConversation: () => void;
}

interface State {
  messages: Message[];
  isLoading: boolean;
  domain: string;
  userId: string;
  domains: Domain[];
  domainsError: string;
  streamingId: string | null;
  plan: PlanSnapshot;
  threadSub: string;
}

type Action =
  | { type: 'SET_DOMAIN'; domain: string }
  | { type: 'SET_USER_ID'; userId: string }
  | { type: 'SET_DOMAINS'; domains: Domain[] }
  | { type: 'SET_DOMAINS_ERROR'; err: string }
  | { type: 'ADD_USER_MSG'; msg: Message }
  | { type: 'START_ASSISTANT'; id: string }
  | { type: 'APPEND_TOKEN'; id: string; token: string }
  | { type: 'FINALIZE' }
  | { type: 'REPLACE_WITH_ERROR'; id: string; detail: string }
  | { type: 'SET_PLAN'; plan: PlanSnapshot }
  | { type: 'CLEAR_PLAN' }
  | { type: 'CLEAR'; threadSub: string };

const EMPTY_PLAN: PlanSnapshot = { todos: [], updated_at: null };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'SET_DOMAIN':
      return { ...state, domain: action.domain };
    case 'SET_USER_ID':
      return { ...state, userId: action.userId };
    case 'SET_DOMAINS':
      return { ...state, domains: action.domains, domainsError: '' };
    case 'SET_DOMAINS_ERROR':
      return { ...state, domainsError: action.err };
    case 'ADD_USER_MSG':
      return {
        ...state,
        messages: [...state.messages, action.msg],
        isLoading: true,
      };
    case 'START_ASSISTANT':
      return {
        ...state,
        streamingId: action.id,
        messages: [
          ...state.messages,
          { id: action.id, role: 'assistant', content: '', timestamp: new Date() },
        ],
      };
    case 'APPEND_TOKEN':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.id ? { ...m, content: m.content + action.token } : m,
        ),
      };
    case 'FINALIZE':
      return { ...state, isLoading: false, streamingId: null };
    case 'REPLACE_WITH_ERROR':
      return {
        ...state,
        isLoading: false,
        streamingId: null,
        messages: state.messages.map((m) =>
          m.id === action.id
            ? { ...m, role: 'error', content: action.detail }
            : m,
        ),
      };
    case 'SET_PLAN':
      return { ...state, plan: action.plan };
    case 'CLEAR_PLAN':
      return { ...state, plan: EMPTY_PLAN };
    case 'CLEAR':
      return {
        ...state,
        messages: [],
        isLoading: false,
        streamingId: null,
        plan: EMPTY_PLAN,
        threadSub: action.threadSub,
      };
    default:
      return state;
  }
}

const ChatContext = createContext<ChatContextValue | null>(null);

// Pre-seed domain from ?domain= query string so a deep-link lands on the
// requested pack without flicker.
function initialDomainFromUrl(): string {
  if (typeof window === 'undefined') return '';
  const params = new URLSearchParams(window.location.search);
  return params.get('domain') || '';
}

const initialState: State = {
  messages: [],
  isLoading: false,
  domain: initialDomainFromUrl(),
  userId: 'demo-user',
  domains: [],
  domainsError: '',
  streamingId: null,
  plan: EMPTY_PLAN,
  threadSub: genId(),
};

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const loadingRef = useRef(false);

  // Fetch the domain list once on mount; pick a default if none was deep-linked.
  useEffect(() => {
    let cancelled = false;
    fetchDomains()
      .then((domains) => {
        if (cancelled) return;
        dispatch({ type: 'SET_DOMAINS', domains });
        if (!state.domain && domains.length > 0) {
          const preferred = domains.find((d) => d.name === 'reference') || domains[0];
          dispatch({ type: 'SET_DOMAIN', domain: preferred.name });
        } else if (state.domain && !domains.find((d) => d.name === state.domain)) {
          // Deep-linked domain was invalid; fall back.
          const fallback = domains[0];
          if (fallback) dispatch({ type: 'SET_DOMAIN', domain: fallback.name });
        }
      })
      .catch((err) => {
        if (!cancelled)
          dispatch({
            type: 'SET_DOMAINS_ERROR',
            err: err instanceof Error ? err.message : 'Failed to load domains',
          });
      });
    return () => {
      cancelled = true;
    };
    // Intentionally empty deps — we want this once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the URL query string in sync with the active domain for shareable links.
  useEffect(() => {
    if (typeof window === 'undefined' || !state.domain) return;
    const url = new URL(window.location.href);
    if (url.searchParams.get('domain') !== state.domain) {
      url.searchParams.set('domain', state.domain);
      window.history.replaceState({}, '', url.toString());
    }
  }, [state.domain]);

  const setDomain = useCallback((d: string) => {
    dispatch({ type: 'SET_DOMAIN', domain: d });
    dispatch({ type: 'CLEAR', threadSub: genId() });
  }, []);

  const setUserId = useCallback((u: string) => {
    dispatch({ type: 'SET_USER_ID', userId: u });
  }, []);

  const newConversation = useCallback(() => {
    loadingRef.current = false;
    dispatch({ type: 'CLEAR', threadSub: genId() });
  }, []);

  const sendMessage = useCallback(
    (message: string) => {
      const trimmed = message.trim();
      if (!trimmed || loadingRef.current) return;
      if (!state.domain || !state.userId) return;
      loadingRef.current = true;

      const userMsg: Message = {
        id: genId(),
        role: 'user',
        content: trimmed,
        timestamp: new Date(),
      };
      dispatch({ type: 'ADD_USER_MSG', msg: userMsg });

      const assistantId = genId();
      dispatch({ type: 'START_ASSISTANT', id: assistantId });

      // Backend scopes checkpointer / chat_history / plans / VFS by
      // `{user}:{domain}:{sub}`. We mint a fresh `sub` per conversation so
      // "New Conversation" (or a domain switch) starts with an empty plan
      // namespace instead of inheriting the previous turn's todos.
      const sub = state.threadSub;
      const threadIdForPlan = `${state.userId}:${state.domain}:${sub}`;

      // Poll /plans while the stream is in flight so the drawer shows todos
      // as the planner writes them (the backend upserts a snapshot on every
      // write_todos tool call). Stop polling as soon as the stream ends.
      const refreshPlan = () => {
        fetchPlan(state.userId, threadIdForPlan, state.domain)
          .then((plan) => dispatch({ type: 'SET_PLAN', plan }))
          .catch(() => {
            /* keep the last known plan on error */
          });
      };
      const pollId = window.setInterval(refreshPlan, 1500);

      streamChat(
        { user_id: state.userId, thread_id: sub, message: trimmed },
        state.domain,
        {
          onToken: (tok) => dispatch({ type: 'APPEND_TOKEN', id: assistantId, token: tok }),
          onDone: () => {
            window.clearInterval(pollId);
            dispatch({ type: 'FINALIZE' });
            loadingRef.current = false;
            // One final refresh after done so the drawer reflects the
            // last write_todos snapshot persisted by the backend.
            refreshPlan();
          },
          onError: (detail) => {
            window.clearInterval(pollId);
            dispatch({ type: 'REPLACE_WITH_ERROR', id: assistantId, detail });
            loadingRef.current = false;
          },
        },
      );
    },
    [state.domain, state.userId, state.threadSub],
  );

  return (
    <ChatContext.Provider
      value={{
        messages: state.messages,
        isLoading: state.isLoading,
        domain: state.domain,
        userId: state.userId,
        domains: state.domains,
        domainsError: state.domainsError,
        plan: state.plan,
        setDomain,
        setUserId,
        sendMessage,
        newConversation,
      }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export function useChat(): ChatContextValue {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChat must be used within ChatProvider');
  return ctx;
}
