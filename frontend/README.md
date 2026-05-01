# LLM RPG Engine - Frontend

This is the frontend application for the LLM RPG Engine, a narrative RPG system powered by LLMs with perspective-aware memory. Built with Next.js, TypeScript, and Tailwind CSS.

## Features

- **Modern Stack**: Next.js 14+ with App Router, TypeScript, Tailwind CSS
- **Authentication**: JWT-based auth with login/register
- **Game Interface**: Rich narrative display with real-time updates
- **Save Management**: Multiple save slots with auto and manual saving
- **Combat UI**: Turn-based combat interface
- **Admin Panel**: Content management for world configuration
- **Responsive Design**: Works on desktop and mobile

## Quick Start

### Prerequisites

- Node.js 20+
- Backend API running on localhost:8000

### Installation

```bash
cd frontend
npm install
```

### Environment Setup

Create `.env.local` file:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Development Server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Available Scripts

```bash
# Development server
npm run dev

# Build for production
npm run build

# Start production server
npm run start

# Run linting
npm run lint

# Run tests
npm test

# Run tests in watch mode
npm run test:watch
```

## Project Structure

```
frontend/
├── app/                    # Next.js App Router
│   ├── layout.tsx         # Root layout
│   ├── page.tsx           # Home page
│   ├── login/             # Login page
│   ├── register/          # Registration page
│   ├── game/              # Game interface
│   ├── saves/             # Save management
│   ├── admin/             # Admin panel
│   └── globals.css        # Global styles
├── components/            # React components
│   ├── ui/               # UI components
│   ├── auth/             # Auth-related components
│   ├── game/             # Game interface components
│   └── admin/            # Admin panel components
├── hooks/                # Custom React hooks
├── lib/                  # Utility functions
├── types/                # TypeScript types
├── public/               # Static assets
└── tests/                # Test files
```

## Backend Integration

The frontend communicates with the LLM RPG Engine backend API:

- **Base URL**: `http://localhost:8000` (configurable via env)
- **Authentication**: JWT tokens stored in localStorage
- **API Docs**: Available at `http://localhost:8000/docs`

### Key API Endpoints

- `POST /auth/login` - User login
- `POST /auth/register` - User registration
- `GET /saves` - List save slots
- `POST /game/sessions/{id}/turn` - Execute game turn
- `POST /streaming/sessions/{id}/turn` - Stream turn narration (SSE)

## Architecture

### State Management

- **Local State**: React useState for component state
- **Server State**: Direct API calls with caching
- **Auth State**: JWT stored in localStorage, user context

### Styling

- **Framework**: Tailwind CSS
- **Components**: Custom components with Tailwind
- **Responsive**: Mobile-first approach

### Type Safety

- **TypeScript**: Strict mode enabled
- **API Types**: Shared types between frontend and backend
- **Validation**: Runtime validation with Zod (optional)

## Development Guidelines

### Adding New Pages

1. Create directory under `app/`
2. Add `page.tsx` with default export
3. Update navigation if needed
4. Add tests

### Adding Components

1. Create component in `components/` subdirectory
2. Use TypeScript props interface
3. Add to index export if shared
4. Write tests

### API Integration

1. Create hook in `hooks/` for data fetching
2. Handle loading and error states
3. Use TypeScript for response types
4. Add error boundaries

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NEXT_PUBLIC_API_URL` | Backend API URL | `http://localhost:8000` |

## Troubleshooting

### Build Errors

```bash
# Clear Next.js cache
rm -rf .next
npm run build
```

### API Connection Issues

1. Verify backend is running: `curl http://localhost:8000/health`
2. Check CORS settings in backend `.env`
3. Verify `NEXT_PUBLIC_API_URL` is set correctly

### Type Errors

```bash
# Regenerate types if needed
npm run type-check
```

## Deployment

### Vercel (Recommended)

```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
vercel
```

### Docker

```bash
# Build image
docker build -t llm-rpg-frontend .

# Run container
docker run -p 3000:3000 -e NEXT_PUBLIC_API_URL=http://backend:8000 llm-rpg-frontend
```

## Learn More

- [Next.js Documentation](https://nextjs.org/docs)
- [LLM RPG Engine Backend](../backend/README.md)
- [Project Documentation](../doc/)

## License

[Project License](../LICENSE)
