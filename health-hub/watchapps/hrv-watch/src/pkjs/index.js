/* Upload-only pairing and a durable multi-session queue on the phone. */
var ENDPOINT='https://pebble-health.example.lan/fitness/hrv';
var AUTH_TOKEN=localStorage.getItem('pebblefit_hrv_token')||'';
var uploading=false;
var retryTimer=null,retryAttempt=0;
var RETRY_BASE_MS=5000,RETRY_MAX_MS=300000,RETRY_LIMIT=8;
function queue(){try{return JSON.parse(localStorage.getItem('pebblefit_hrv_queue')||'[]');}catch(e){return [];}}
function store(q){localStorage.setItem('pebblefit_hrv_queue',JSON.stringify(q));}
function clearRetry(){if(retryTimer!==null){clearTimeout(retryTimer);retryTimer=null;}}
function retryLater(){
 if(retryTimer!==null||retryAttempt>=RETRY_LIMIT)return;
 var delay=Math.min(RETRY_MAX_MS,RETRY_BASE_MS*Math.pow(2,retryAttempt++));
 retryTimer=setTimeout(function(){retryTimer=null;upload();},delay);
}
function reply(code,ts){var msg={ack:code};if(ts)msg.ack_ts=ts;Pebble.sendAppMessage(msg);}
function decode(bytes,width){var result=[];for(var i=0;i<bytes.length;i+=width){var n=0;for(var j=0;j<width;j++)n+=(bytes[i+j]&255)*Math.pow(256,j);result.push(n);}return result;}
function decodeExact(bytes,width,length){
 if(!bytes||bytes.length!==width*length)return null;
 for(var i=0;i<bytes.length;i++)if(typeof bytes[i]!=='number'||!isFinite(bytes[i])||Math.floor(bytes[i])!==bytes[i]||bytes[i]<0||bytes[i]>255)return null;
 return decode(bytes,width);
}
function decodeSigned(bytes){return decode(bytes,4).map(function(v){return v>2147483647?v-4294967296:v;});}
function motionWindows(p){
 if(p.collector_version!==153||p.motion_window_version!==1||p.motion_window_ms!==5000)return null;
 var totals=decodeExact(p.motion_window_totals,4,36),samples=decodeExact(p.motion_window_samples,2,36);
 var transitions=decodeExact(p.motion_window_transitions,2,36),peaks=decodeExact(p.motion_window_peaks,4,36);
 if(!totals||!samples||!transitions||!peaks)return null;
 var windows=[];for(var i=0;i<36;i++)windows.push({start_ms:i*5000,samples:samples[i],transitions:transitions[i],total_delta:totals[i],max_delta:peaks[i]});
 return {version:1,window_ms:5000,clock:'callback_receipt',windows:windows};
}
function diagnostic(p){
 if(!AUTH_TOKEN)return;
 var req=new XMLHttpRequest();req.open('POST',ENDPOINT,true);req.timeout=10000;
 req.setRequestHeader('Content-Type','application/json');req.setRequestHeader('Authorization','Bearer '+AUTH_TOKEN);
 req.onload=function(){};req.onerror=function(){};req.ontimeout=function(){};
 req.send(JSON.stringify({collector:true,ts:p.ts,collector_version:p.collector_version,schedule_ok:p.schedule_ok,schedule_error:p.schedule_error,next_wakeup:p.next_wakeup,nights_enabled:!!p.night,firmware:p.firmware||'unknown',phase:p.phase||1,launch:p.launch?'scheduled':'manual',schedule_ids:p.schedule_ids?decodeSigned(p.schedule_ids):[],schedule_times:p.schedule_times?decode(p.schedule_times,4):[]}));
}
function preflight(){
 if(!AUTH_TOKEN){reply(2);return;}
 var req=new XMLHttpRequest();req.open('GET',ENDPOINT,true);req.timeout=10000;
 req.setRequestHeader('Authorization','Bearer '+AUTH_TOKEN);
 req.onload=function(){reply(req.status===200?10:req.status===401?3:1000+req.status);};
 req.onerror=function(){reply(4);};req.ontimeout=function(){reply(5);};req.send();
}
function upload(){
 if(uploading)return;
 var q=queue();if(!q.length){retryAttempt=0;clearRetry();preflight();return;}
 if(!AUTH_TOKEN){reply(2,q[0].ts);return;}
 var sample=q[0],req=new XMLHttpRequest();uploading=true;
 req.open('POST',ENDPOINT,true);req.timeout=20000;
 req.setRequestHeader('Content-Type','application/json');req.setRequestHeader('Authorization','Bearer '+AUTH_TOKEN);
 req.onload=function(){
  uploading=false;
  if(req.status>=200&&req.status<300){
   retryAttempt=0;clearRetry();store(queue().filter(function(s){return s.ts!==sample.ts;}));reply(1,sample.ts);
   if(queue().length)upload();
  }else if(req.status===401){reply(3,sample.ts);}
  else {
   reply(1000+req.status,sample.ts);
   if(req.status===408||req.status===429||req.status>=500)retryLater();
  }
 };
 req.onerror=function(){uploading=false;reply(4,sample.ts);retryLater();};
 req.ontimeout=function(){uploading=false;reply(5,sample.ts);retryLater();};req.send(JSON.stringify(sample));
}
Pebble.addEventListener('showConfiguration',function(){Pebble.openURL('https://pebble-health.example.lan/pair?kind=hrv');});
Pebble.addEventListener('webviewclosed',function(e){
 if(!e.response||e.response==='CANCELLED')return;
 try{var data=JSON.parse(decodeURIComponent(e.response));if(data.token){AUTH_TOKEN=data.token;localStorage.setItem('pebblefit_hrv_token',data.token);upload();}}catch(err){reply(2);}
});
Pebble.addEventListener('ready',function(){
 var old=localStorage.getItem('pebblefit_hrv_pending');
 if(old){try{var s=JSON.parse(old),q=queue();if(!q.some(function(x){return x.ts===s.ts;})){q.push(s);store(q);}localStorage.removeItem('pebblefit_hrv_pending');}catch(e){}}
 upload();
});
Pebble.addEventListener('appmessage',function(e){
 var p=e.payload;if(p.command){if(p.command===2)diagnostic(p);upload();return;}
 if(!p.ppi||!p.offsets){reply(6);return;}
 var sample={ts:p.ts,ppi:decode(p.ppi,2),offsets_ms:decode(p.offsets,4),motion_total:p.motion,scheduled:!!p.night,motion_samples:p.motion_samples||0,collector_version:p.collector_version||0,accel_callbacks:p.accel_callbacks||0,vibration_samples:p.vibration_samples||0,accel_rate_result:p.accel_rate_result||0,motion_source:p.motion_source===1?'raw_accelerometer':'processed_accelerometer',firmware:p.firmware||'unknown',hrv_events:p.hrv_events||0,zero_ppi_events:p.zero_ppi_events||0,hr_events:p.hr_events||0,hr_sum:p.hr_sum||0,hr_valid:p.hr_valid||0,capacity_limited:!!p.capacity_limited,stream_semantics:'latest_ppi_updates'};
 var windows=motionWindows(p);if(windows)sample.motion_windows=windows;
 var q=queue(),existing=q.some(function(x){return x.ts===sample.ts;});
 if(!existing&&q.length>=128){reply(7,sample.ts);return;}
 try{if(!existing){q.push(sample);store(q);}reply(11,sample.ts);upload();}catch(e){reply(7,sample.ts);}
});
