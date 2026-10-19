import {
  IconHeartbeat,
  IconListDetails,
  IconSettings,
  IconShieldCog,
  IconUser,
  type Icon,
} from '@tabler/icons-react'

export interface NavItem {
  label: string
  to: string
  icon: Icon
}

export const navItems: NavItem[] = [
  { label: 'Player', to: '/player', icon: IconUser },
  { label: 'Admin', to: '/admin', icon: IconShieldCog },
  { label: 'Settings', to: '/settings', icon: IconSettings },
  { label: 'Health', to: '/health', icon: IconHeartbeat },
  { label: 'Audit log', to: '/audit', icon: IconListDetails },
]
