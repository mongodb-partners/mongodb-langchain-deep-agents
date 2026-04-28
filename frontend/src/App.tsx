import React from 'react';
import { ChatProvider } from './context/ChatContext';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import PlanDrawer from './components/PlanDrawer';

const appStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  height: '100vh',
  overflow: 'hidden',
};

const mainStyle: React.CSSProperties = {
  display: 'flex',
  flex: 1,
  overflow: 'hidden',
};

export default function App() {
  return (
    <ChatProvider>
      <div style={appStyle}>
        <Header />
        <div style={mainStyle}>
          <Sidebar />
          <ChatArea />
          <PlanDrawer />
        </div>
      </div>
    </ChatProvider>
  );
}
