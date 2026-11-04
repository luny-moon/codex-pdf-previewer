(() => {
  if (window.location.protocol === 'file:') {
    document.getElementById('status').textContent = '请通过插件打开 PDF；阅读器需要本机 HTTP 服务。';
    document.getElementById('filename').textContent = '通过高清 PDF 预览插件启动';
    return;
  }
  import('./reader.js').catch(error => {
    console.error('PDF reader bootstrap failed', error);
    document.getElementById('filename').textContent = '阅读器加载失败';
    document.getElementById('status').textContent = '阅读器未能加载，请刷新重试。';
    document.getElementById('refresh').addEventListener('click', () => window.location.reload());
  });
})();
