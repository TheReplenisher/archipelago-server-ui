import { IconHeartbeat, IconShieldCog, IconUser, type Icon } from '@tabler/icons-react'

export interface NavItem {
  label: string
  to: string
  icon: Icon
}

export const navItems: NavItem[] = [
  { label: 'Player', to: '/player', icon: IconUser },
  { label: 'Admin', to: '/admin', icon: IconShieldCog },
  { label: 'Health', to: '/health', icon: IconHeartbeat },
]
