(() => {
  if (document.getElementById('time-machine-launcher')) return;
  const link = document.createElement('a');
  link.id = 'time-machine-launcher';
  link.textContent = '↶ Time Machine';
  link.href = 'http://127.0.0.1:8765';
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.setAttribute('aria-label', 'Open local Time Machine recovery workspace');
  Object.assign(link.style, {position:'fixed',bottom:'24px',right:'24px',zIndex:'2147483647',padding:'13px 18px',background:'#102d2d',color:'#effff7',border:'1px solid #78cbb3',borderRadius:'12px',font:'600 14px system-ui',textDecoration:'none',boxShadow:'0 8px 28px #0003'});
  document.body.append(link);
})();
