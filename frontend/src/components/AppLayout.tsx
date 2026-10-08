import { AppShell, Burger, Button, Group, NavLink as MantineNavLink, Title } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { NavLink, Outlet, useLocation } from 'react-router'
import { ColorSchemeToggle } from './ColorSchemeToggle'
import { navItems } from './navItems'

export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure()
  const { pathname } = useLocation()
  const isActive = (to: string) => pathname === to || pathname.startsWith(`${to}/`)

  return (
    <AppShell
      header={{ height: 56 }}
      // The navbar is the mobile menu only; on wider screens the tabs live in the header.
      navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: !opened, desktop: true } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
              aria-label="Toggle navigation"
            />
            <Title order={1} size="h4" lineClamp={1}>
              Archipelago Server UI
            </Title>
          </Group>
          <Group gap="xs" wrap="nowrap">
            <Group gap={4} visibleFrom="sm" component="nav" aria-label="Main">
              {navItems.map((item) => (
                <Button
                  key={item.to}
                  component={NavLink}
                  to={item.to}
                  variant={isActive(item.to) ? 'light' : 'subtle'}
                  leftSection={<item.icon size={18} stroke={1.5} />}
                >
                  {item.label}
                </Button>
              ))}
            </Group>
            <ColorSchemeToggle />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs" component="nav" aria-label="Main (mobile)">
        {navItems.map((item) => (
          <MantineNavLink
            key={item.to}
            component={NavLink}
            to={item.to}
            label={item.label}
            leftSection={<item.icon size={18} stroke={1.5} />}
            active={isActive(item.to)}
            onClick={close}
          />
        ))}
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  )
}
