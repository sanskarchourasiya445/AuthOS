import React from 'react'

interface BadgeProps {
  status: string
  className?: string
  children?: React.ReactNode
}

export const Badge: React.FC<BadgeProps> = ({ status, className = '', children }) => {
  const normalized = status.toUpperCase().replace(/\s+/g, '_')
  const badgeClass = `badge badge-${normalized} ${className}`.trim()

  return (
    <span className={badgeClass} role="status">
      {children || status}
    </span>
  )
}
