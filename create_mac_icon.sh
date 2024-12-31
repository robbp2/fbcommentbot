#!/bin/bash

# Convert webp to png if it exists
if [ -f "icon.webp" ]; then
    magick convert icon.webp icon_original.png
else
    echo "Please ensure icon.webp exists in the current directory"
    exit 1
fi

# Create iconset directory
mkdir icon.iconset

# Function to create rounded icon
create_rounded_icon() {
    size=$1
    input=$2
    output=$3
    radius=$4
    
    magick convert "$input" -resize ${size}x${size} \
        \( +clone -alpha extract \
            -draw "fill white rectangle 0,0 ${size},${size}" \
            -draw "fill black roundrectangle 0,0 ${size},${size} $radius,$radius" \
            -negate \
        \) \
        -alpha off -compose CopyOpacity -composite \
        "$output"
}

# Create rounded icons for each size
create_rounded_icon 16 icon_original.png icon.iconset/icon_16x16.png 4
create_rounded_icon 32 icon_original.png icon.iconset/icon_16x16@2x.png 8
create_rounded_icon 32 icon_original.png icon.iconset/icon_32x32.png 8
create_rounded_icon 64 icon_original.png icon.iconset/icon_32x32@2x.png 16
create_rounded_icon 128 icon_original.png icon.iconset/icon_128x128.png 32
create_rounded_icon 256 icon_original.png icon.iconset/icon_128x128@2x.png 64
create_rounded_icon 256 icon_original.png icon.iconset/icon_256x256.png 64
create_rounded_icon 512 icon_original.png icon.iconset/icon_256x256@2x.png 128
create_rounded_icon 512 icon_original.png icon.iconset/icon_512x512.png 128
create_rounded_icon 1024 icon_original.png icon.iconset/icon_512x512@2x.png 256

# Convert to icns
iconutil -c icns icon.iconset

# Clean up
rm -rf icon.iconset
rm icon_original.png