import React from 'react';

export interface SidebarProps {
  activeTab?: string;
  onSelectTab?: (tab: string) => void;
  isOpen?: boolean;
  onClose?: () => void;
}

/**
 * Sidebar is deprecated in the new horizontal top-header layout.
 * Navigation is now rendered in TopBar header.
 */
export const Sidebar: React.FC<SidebarProps> = () => {
  return null;
};

export default Sidebar;
