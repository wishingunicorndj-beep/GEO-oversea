#!/usr/bin/env ruby

require "fileutils"

FILES = %w[
  geo-query.yml
  geo-analysis.yml
  geo-summary.yml
  geo-article.yml
].freeze

if ARGV.length != 2
  warn "Usage: ruby scripts/sanitize_exports.rb SOURCE_WORKFLOWS_DIR TARGET_WORKFLOWS_DIR"
  exit 2
end

source_dir = File.expand_path(ARGV[0])
target_dir = File.expand_path(ARGV[1])
FileUtils.mkdir_p(target_dir)

missing = FILES.reject { |name| File.file?(File.join(source_dir, name)) }
unless missing.empty?
  warn "Missing workflow files: #{missing.join(', ')}"
  exit 3
end

FILES.each do |name|
  source = File.join(source_dir, name)
  target = File.join(target_dir, name)
  content = File.binread(source)
  content.gsub!(
    /(Authorization:Bearer\s*)[A-Za-z0-9._~+\/=:-]{20,}/i,
    '\1__GIT_REDACTED_TOKEN__'
  )
  File.binwrite(target, content)
end

remaining = []
FILES.each do |name|
  path = File.join(target_dir, name)
  File.foreach(path, encoding: "UTF-8").with_index(1) do |line, number|
    if line.match?(/Authorization:Bearer\s*(?!__GIT_REDACTED_TOKEN__)[A-Za-z0-9._~+\/=:-]{20,}/i)
      remaining << "#{name}:#{number}"
    end
  end
end

unless remaining.empty?
  warn "Unredacted bearer credentials remain at: #{remaining.join(', ')}"
  exit 4
end

puts "Sanitized #{FILES.length} workflow files into #{target_dir}"
