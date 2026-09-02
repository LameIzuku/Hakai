$root = $PSScriptRoot
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:4173/")
$listener.Start()
Write-Output "Serving $root on http://localhost:4173/"

$mime = @{
  ".html" = "text/html; charset=utf-8"
  ".js"   = "text/javascript"
  ".css"  = "text/css"
  ".png"  = "image/png"
  ".jpg"  = "image/jpeg"
  ".obj"  = "text/plain"
  ".mtl"  = "text/plain"
  ".json" = "application/json"
  ".ico"  = "image/x-icon"
}

while ($listener.IsListening) {
  try {
    $ctx = $listener.GetContext()
    $req = $ctx.Request
    $res = $ctx.Response
    $path = [System.Uri]::UnescapeDataString($req.Url.AbsolutePath)
    if ($path -eq "/") { $path = "/index.html" }
    $file = Join-Path $root ($path -replace "/", "\").TrimStart("\")
    $fullRoot = [System.IO.Path]::GetFullPath($root)
    $fullFile = [System.IO.Path]::GetFullPath($file)
    if ($fullFile.StartsWith($fullRoot) -and (Test-Path $fullFile -PathType Leaf)) {
      $ext = [System.IO.Path]::GetExtension($fullFile).ToLower()
      $type = $mime[$ext]
      if (-not $type) { $type = "application/octet-stream" }
      $bytes = [System.IO.File]::ReadAllBytes($fullFile)
      $res.ContentType = $type
      $res.ContentLength64 = $bytes.Length
      $res.OutputStream.Write($bytes, 0, $bytes.Length)
    } else {
      $res.StatusCode = 404
      $msg = [System.Text.Encoding]::UTF8.GetBytes("404")
      $res.OutputStream.Write($msg, 0, $msg.Length)
    }
    $res.OutputStream.Close()
  } catch {
    Write-Output "ERR: $_"
  }
}
