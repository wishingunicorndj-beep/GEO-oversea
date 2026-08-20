#!/usr/bin/env ruby

require "digest"
require "json"

root = File.expand_path("..", __dir__)
manifest = JSON.parse(File.read(File.join(root, "manifest.json")))

manifest.fetch("workflows").each do |id, config|
  path = File.join(root, config.fetch("path"))
  unless File.file?(path)
    puts "#{id}\tmissing\t#{path}"
    next
  end

  hash = Digest::SHA256.file(path).hexdigest[0, 12]
  puts [id, config.fetch("version"), hash, config.fetch("path")].join("\t")
end
