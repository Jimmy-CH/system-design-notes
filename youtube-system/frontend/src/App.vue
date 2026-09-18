<template>
  <div class="app">
    <nav class="navbar">
      <RouterLink to="/" class="logo"><span class="play">▶</span> MyTube</RouterLink>
      <RouterLink to="/upload" class="btn">Upload</RouterLink>
    </nav>
    <main class="content">
      <RouterView />
    </main>
  </div>
</template>
