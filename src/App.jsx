import { useEffect, useState } from 'react';
import Header from './components/Header.jsx';
import ChatWindow from './components/Chat/ChatWindow.jsx';
import EmployeeInventoryChat from './components/Chat/EmployeeInventoryChat.jsx';
import ModeLanding from './components/ModeLanding.jsx';
import { branches, defaultBranch } from './config/branches.js';

const defaultRole = 'Cliente';
const BRANCH_STORAGE_KEY = 'rio-claro-branch';
const CHAT_TEXT_SIZE_STORAGE_KEY = 'rio-claro-chat-text-size';
const CHAT_TEXT_SIZES = ['small', 'normal', 'large'];

function getStoredPreference(key, validValues, fallback) {
  try {
    const storedValue = window.localStorage.getItem(key);
    return validValues.includes(storedValue) ? storedValue : fallback;
  } catch {
    return fallback;
  }
}

export default function App() {
  const [appMode, setAppMode] = useState('home');
  const [selectedBranch, setSelectedBranch] = useState(() => {
    const branchId = getStoredPreference(BRANCH_STORAGE_KEY, branches.map((branch) => branch.id), defaultBranch.id);
    return branches.find((branch) => branch.id === branchId) ?? defaultBranch;
  });
  const [selectedRole, setSelectedRole] = useState(defaultRole);
  const [chatTextSize, setChatTextSize] = useState(
    () => getStoredPreference(CHAT_TEXT_SIZE_STORAGE_KEY, CHAT_TEXT_SIZES, 'normal'),
  );
  const [preferenceNotice, setPreferenceNotice] = useState('');

  useEffect(() => {
    document.documentElement.dataset.chatTextSize = chatTextSize;
  }, [chatTextSize]);

  function updateBranch(branch) {
    setSelectedBranch(branch);
    try {
      window.localStorage.setItem(BRANCH_STORAGE_KEY, branch.id);
      setPreferenceNotice('');
    } catch {
      setPreferenceNotice('La sucursal se cambió, pero no se pudo guardar como preferencia en este navegador.');
    }
  }

  function updateChatTextSize(size) {
    if (!CHAT_TEXT_SIZES.includes(size)) return;
    setChatTextSize(size);
    try {
      window.localStorage.setItem(CHAT_TEXT_SIZE_STORAGE_KEY, size);
      setPreferenceNotice('');
    } catch {
      setPreferenceNotice('El tamaño del texto se cambió, pero no se pudo guardar como preferencia en este navegador.');
    }
  }

  return (
    <div className="app-shell">
      <Header
        appMode={appMode}
        onReturnHome={() => setAppMode('home')}
        branches={branches}
        selectedBranch={selectedBranch}
        onSelectBranch={updateBranch}
        selectedRole={selectedRole}
        onSelectRole={setSelectedRole}
        chatTextSize={chatTextSize}
        onSelectChatTextSize={updateChatTextSize}
        preferenceNotice={preferenceNotice}
      />
      <main
        className={`app-main${appMode === 'home' ? ' app-main-home' : ''}`}
        aria-label="Distribuidora Río Claro"
      >
        {appMode === 'home' && <ModeLanding onSelectMode={setAppMode} />}
        {appMode === 'customer' && (
          <ChatWindow selectedBranch={selectedBranch} selectedRole={selectedRole} />
        )}
        {appMode === 'warehouse' && <EmployeeInventoryChat />}
      </main>
    </div>
  );
}
