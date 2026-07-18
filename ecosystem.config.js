module.exports = {
  apps: [
    {
      name: "workos-api",
      cwd: "/root/workos/backend",
      script: "/root/workos/.venv/bin/python",
      args: "-m uvicorn main:app --host 127.0.0.1 --port 8011",
      autorestart: true,
      max_restarts: 10,
    },
  ],
};
